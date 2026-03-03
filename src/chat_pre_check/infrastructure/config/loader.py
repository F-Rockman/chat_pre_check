from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chat_pre_check.infrastructure.config.validator import validate_config


@dataclass(slots=True)
class AppConfig:
    """运行时配置聚合对象。"""
    capabilities: list[dict[str, Any]]
    scenes: list[dict[str, Any]]
    templates: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    seed_cases: list[dict[str, Any]]
    rules: dict[str, Any]
    thresholds: dict[str, float]
    vector: dict[str, Any]
    slot_policies: dict[str, Any]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_app_config(config_dir: str | Path) -> AppConfig:
    """加载并编译配置：capabilities -> scenes/templates/cases/seed_cases。"""
    root = Path(config_dir)
    capabilities_payload = _load_json(root / "capabilities.json")
    capabilities, slot_policy_defaults = _parse_capabilities_payload(capabilities_payload)
    scenes, templates, cases, seed_cases, slot_policies = _compile_capabilities(
        capabilities=capabilities,
        slot_policy_defaults=slot_policy_defaults,
    )
    config = AppConfig(
        capabilities=capabilities,
        scenes=scenes,
        templates=templates,
        cases=cases,
        seed_cases=seed_cases,
        rules=_load_json(root / "rules.json"),
        thresholds=_load_json(root / "thresholds.json"),
        vector=_load_json(root / "vector.json"),
        slot_policies=slot_policies,
    )
    validate_config(config)
    return config


def _parse_capabilities_payload(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """兼容 capabilities.json 两种格式：数组或对象包装。"""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], {}
    if not isinstance(payload, dict):
        raise ValueError("capabilities.json must be object or array")
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise ValueError("capabilities.capabilities must be list")
    slot_policy_defaults = payload.get("slot_policy_defaults", {})
    if slot_policy_defaults is None:
        slot_policy_defaults = {}
    if not isinstance(slot_policy_defaults, dict):
        raise ValueError("capabilities.slot_policy_defaults must be object")
    return [item for item in capabilities if isinstance(item, dict)], slot_policy_defaults


def _compile_capabilities(
    *,
    capabilities: list[dict[str, Any]],
    slot_policy_defaults: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """将业务能力定义编译为运行时视图结构。"""
    scenes: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    seed_cases: list[dict[str, Any]] = []

    scene_slot_policies: dict[str, Any] = {}
    for cap in capabilities:
        capability_id = str(cap.get("capability_id", "")).strip()
        if not capability_id:
            continue
        enabled = bool(cap.get("enabled", True))
        scope = _to_dict(cap.get("scope"))
        slots = _to_dict(cap.get("slots"))

        scenes.append(
            {
                "scene_id": capability_id,
                "description": str(cap.get("description", "")).strip(),
                "required_slots": _to_str_list(slots.get("required")),
                "conditional_slots": _to_list_of_dict(slots.get("conditional")),
                "defaults": _to_dict(slots.get("defaults")),
                "clarify_policy": _to_dict(slots.get("clarify_policy")),
                "keywords": _to_str_list(scope.get("keywords")),
                "examples": _to_str_list(scope.get("examples")),
                "enabled": enabled,
            }
        )

        (
            intent_templates,
            intent_seed_cases,
            intent_template_ids,
            intent_seed_case_ids,
        ) = _compile_capability_intents(
            capability_id=capability_id,
            enabled=enabled,
            intents=cap.get("intents"),
        )
        templates.extend(intent_templates)
        seed_cases.extend(intent_seed_cases)

        template_list = cap.get("templates", [])
        if isinstance(template_list, list):
            for tpl in template_list:
                if not isinstance(tpl, dict):
                    continue
                template_id = str(tpl.get("template_id", "")).strip()
                if not template_id:
                    continue
                if template_id in intent_template_ids:
                    continue
                template_item = dict(tpl)
                template_item["scene_id"] = capability_id
                template_item.setdefault("slot_schema", {})
                template_item.setdefault("examples", [])
                template_item.setdefault("keywords", [])
                template_item.setdefault("negative_keywords", [])
                template_item.setdefault("enabled", enabled)
                templates.append(template_item)

        recommendations = cap.get("recommendations", [])
        if isinstance(recommendations, list) and recommendations:
            case_id = str(cap.get("recommendation_case_id", "")).strip()
            if not case_id:
                case_id = f"case_{capability_id.replace('.', '_')}"
            cases.append(
                {
                    "case_id": case_id,
                    "scene_id": capability_id,
                    "examples": _to_str_list(scope.get("examples"))[:3],
                    "recommended_actions": _to_list_of_dict(recommendations),
                    "enabled": enabled,
                }
            )

        cap_seed_cases = cap.get("seed_cases", [])
        if isinstance(cap_seed_cases, list):
            for seed in cap_seed_cases:
                if not isinstance(seed, dict):
                    continue
                seed_case_id = str(seed.get("case_id", "")).strip()
                if not seed_case_id:
                    continue
                if seed_case_id in intent_seed_case_ids:
                    continue
                item = dict(seed)
                item["case_id"] = seed_case_id
                item["scene_id"] = capability_id
                item.setdefault("label", str(seed.get("text", seed_case_id)))
                item.setdefault("text", str(seed.get("text", "")))
                item.setdefault("route_type", "route_nl2sql")
                item.setdefault("tags", [])
                item.setdefault("priority", 100)
                item.setdefault("owner", "")
                item.setdefault("risk_level", "medium")
                item.setdefault("enabled", enabled)
                seed_cases.append(item)

        slot_policy = _to_dict(cap.get("slot_policy"))
        if slot_policy:
            scene_slot_policies[capability_id] = slot_policy

    slot_policies = {
        "default": slot_policy_defaults,
        "scenes": scene_slot_policies,
    }
    return scenes, templates, cases, seed_cases, slot_policies


def _compile_capability_intents(
    *,
    capability_id: str,
    enabled: bool,
    intents: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]:
    """编译 capability.intents，拆解为模板视图与 seed 视图。"""
    if not isinstance(intents, list):
        return [], [], set(), set()
    compiled_templates: list[dict[str, Any]] = []
    compiled_seed_cases: list[dict[str, Any]] = []
    template_ids: set[str] = set()
    seed_case_ids: set[str] = set()
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        case_id = str(intent.get("case_id", "")).strip()
        if not case_id:
            continue

        seed_item = _normalize_intent_seed_item(
            intent=intent,
            capability_id=capability_id,
            enabled=enabled,
        )
        if seed_item:
            compiled_seed_cases.append(seed_item)
            seed_case_ids.add(case_id)

        template_item = _normalize_intent_template_item(
            intent=intent,
            capability_id=capability_id,
            enabled=enabled,
        )
        if template_item:
            compiled_templates.append(template_item)
            template_ids.add(template_item["template_id"])
    return compiled_templates, compiled_seed_cases, template_ids, seed_case_ids


def _normalize_intent_seed_item(
    *,
    intent: dict[str, Any],
    capability_id: str,
    enabled: bool,
) -> dict[str, Any] | None:
    """归一化单条 intent 为 seed_case 结构。"""
    case_id = str(intent.get("case_id", "")).strip()
    if not case_id:
        return None
    label = str(intent.get("label", "")).strip()
    text = str(intent.get("text", "")).strip()
    if not text:
        examples = _to_str_list(intent.get("examples"))
        if examples:
            text = examples[0]
    if not text:
        text = label or case_id

    template = _to_dict(intent.get("template"))
    template_id = str(template.get("template_id") or intent.get("template_id", "")).strip()
    route_type = str(intent.get("route_type", "")).strip()
    if not route_type:
        route_type = "route_template" if template_id else "route_nl2sql"

    item = {
        "case_id": case_id,
        "scene_id": capability_id,
        "label": label or text,
        "text": text,
        "route_type": route_type,
        "tags": _to_str_list(intent.get("tags")),
        "priority": _to_int(intent.get("priority"), 100),
        "owner": str(intent.get("owner", "")).strip(),
        "risk_level": str(intent.get("risk_level", "medium")).strip() or "medium",
        "enabled": bool(intent.get("enabled", enabled)),
    }
    if template_id:
        item["template_id"] = template_id
    slots = intent.get("slots")
    if isinstance(slots, dict):
        item["slots"] = slots
    return item


def _normalize_intent_template_item(
    *,
    intent: dict[str, Any],
    capability_id: str,
    enabled: bool,
) -> dict[str, Any] | None:
    """归一化单条 intent 为 template 结构（可选）。"""
    template = _to_dict(intent.get("template"))
    template_id = str(template.get("template_id") or intent.get("template_id", "")).strip()
    if not template_id:
        return None

    slot_schema = _to_dict(template.get("slot_schema"))
    if not slot_schema:
        slot_schema = _to_dict(intent.get("slot_schema"))
    template_item = {
        "template_id": template_id,
        "scene_id": capability_id,
        "slot_schema": {
            "required": _to_str_list(slot_schema.get("required")),
            "optional": _to_str_list(slot_schema.get("optional")),
        },
        "examples": _to_str_list(template.get("examples")) or _to_str_list(intent.get("examples")),
        "keywords": _to_str_list(template.get("keywords")) or _to_str_list(intent.get("keywords")),
        "negative_keywords": _to_str_list(template.get("negative_keywords"))
        or _to_str_list(intent.get("negative_keywords")),
        "enabled": bool(template.get("enabled", intent.get("enabled", enabled))),
    }
    case_id = str(intent.get("case_id", "")).strip()
    if case_id:
        template_item["case_id_ref"] = case_id
    return template_item


def _to_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _to_list_of_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
