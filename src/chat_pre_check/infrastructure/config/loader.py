from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chat_pre_check.infrastructure.config.validator import validate_config


@dataclass(slots=True)
class AppConfig:
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

        template_list = cap.get("templates", [])
        if isinstance(template_list, list):
            for tpl in template_list:
                if not isinstance(tpl, dict):
                    continue
                template_id = str(tpl.get("template_id", "")).strip()
                if not template_id:
                    continue
                template_item = dict(tpl)
                template_item["scene_id"] = capability_id
                template_item.setdefault("slot_schema", {})
                template_item.setdefault("examples", [])
                template_item.setdefault("keywords", [])
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
