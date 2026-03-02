from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chat_pre_check.infrastructure.config.loader import AppConfig


REQUIRED_SCENE_KEYS = {"scene_id", "description", "required_slots", "defaults"}
REQUIRED_TEMPLATE_KEYS = {"template_id", "scene_id", "slot_schema", "examples"}
REQUIRED_THRESHOLD_KEYS = {
    "T_scope",
    "T_template",
    "T_scene_gap",
    "resolver_commit_score",
    "resolver_min_gap",
}
REQUIRED_VECTOR_KEYS = {
    "model_name",
    "device",
    "scene_index",
    "template_index",
    "seed_case_index",
    "scene_topk",
    "template_topk",
    "seed_case_topk",
    "fusion_weights",
    "seed_scope_guard",
    "reindex_on_start",
}


def validate_config(config: "AppConfig") -> None:
    _validate_scene_config(config.scenes)
    _validate_template_config(config.templates, config.scenes)
    _validate_thresholds(config.thresholds)
    _validate_vector(config.vector)
    _validate_rules(config.rules)
    _validate_slot_policies(config.slot_policies)


def _validate_scene_config(scenes: list[dict[str, Any]]) -> None:
    scene_ids = set()
    for scene in scenes:
        missing = REQUIRED_SCENE_KEYS - set(scene.keys())
        if missing:
            raise ValueError(f"Scene config missing keys: {missing}")
        scene_id = scene["scene_id"]
        if scene_id in scene_ids:
            raise ValueError(f"Duplicate scene_id detected: {scene_id}")
        scene_ids.add(scene_id)
        if not isinstance(scene.get("required_slots", []), list):
            raise ValueError(f"Scene required_slots must be list: {scene_id}")
        if not isinstance(scene.get("defaults", {}), dict):
            raise ValueError(f"Scene defaults must be object: {scene_id}")


def _validate_template_config(
    templates: list[dict[str, Any]], scenes: list[dict[str, Any]]
) -> None:
    template_ids = set()
    scene_ids = {scene["scene_id"] for scene in scenes}
    for template in templates:
        missing = REQUIRED_TEMPLATE_KEYS - set(template.keys())
        if missing:
            raise ValueError(f"Template config missing keys: {missing}")
        template_id = template["template_id"]
        if template_id in template_ids:
            raise ValueError(f"Duplicate template_id detected: {template_id}")
        template_ids.add(template_id)
        if template["scene_id"] not in scene_ids:
            raise ValueError(
                f"Template scene_id not found: {template_id} -> {template['scene_id']}"
            )
        schema = template.get("slot_schema", {})
        if not isinstance(schema, dict):
            raise ValueError(f"Template slot_schema must be object: {template_id}")
        if not isinstance(schema.get("required", []), list):
            raise ValueError(f"Template slot_schema.required must be list: {template_id}")
        if not isinstance(schema.get("optional", []), list):
            raise ValueError(f"Template slot_schema.optional must be list: {template_id}")


def _validate_thresholds(thresholds: dict[str, float]) -> None:
    threshold_missing = REQUIRED_THRESHOLD_KEYS - set(thresholds.keys())
    if threshold_missing:
        raise ValueError(f"Threshold config missing keys: {threshold_missing}")
    for key in ("T_scope", "T_template", "T_scene_gap"):
        value = thresholds[key]
        if not (0 <= value <= 1):
            raise ValueError(f"{key} must be in [0, 1], got {value}")
    for key in ("resolver_commit_score", "resolver_min_gap"):
        value = thresholds[key]
        if not (0 <= value <= 1):
            raise ValueError(f"{key} must be in [0, 1], got {value}")


def _validate_vector(vector: dict[str, Any]) -> None:
    vector_missing = REQUIRED_VECTOR_KEYS - set(vector.keys())
    if vector_missing:
        raise ValueError(f"Vector config missing keys: {vector_missing}")
    if (
        vector["scene_topk"] <= 0
        or vector["template_topk"] <= 0
        or vector["seed_case_topk"] <= 0
    ):
        raise ValueError("scene_topk/template_topk/seed_case_topk must be positive")
    search_backend = vector.get("search_backend", "opensearch")
    if str(search_backend).lower() not in {"opensearch", "elasticsearch", "es"}:
        raise ValueError(
            "vector.search_backend must be one of: opensearch, elasticsearch, es"
        )
    fusion = vector.get("fusion_weights", {})
    for key in ("scene", "template"):
        if key not in fusion:
            raise ValueError(f"fusion_weights missing key: {key}")
        weights = fusion[key]
        total = sum(float(v) for v in weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"fusion_weights.{key} must sum to 1.0, got {total}")
    guard = vector.get("seed_scope_guard", {})
    if not isinstance(guard, dict):
        raise ValueError("seed_scope_guard must be object")
    if "enabled" in guard and not isinstance(guard["enabled"], bool):
        raise ValueError("seed_scope_guard.enabled must be bool")
    if "min_score" in guard and not (0 <= float(guard["min_score"]) <= 1):
        raise ValueError("seed_scope_guard.min_score must be in [0,1]")
    if "min_hits" in guard and int(guard["min_hits"]) < 1:
        raise ValueError("seed_scope_guard.min_hits must be >= 1")


def _validate_rules(rules: dict[str, Any]) -> None:
    for key in (
        "unknown_domain_keywords",
        "unsupported_domain_keywords",
        "policy_block_keywords",
        "data_unavailable_keywords",
    ):
        if key in rules and not isinstance(rules[key], list):
            raise ValueError(f"rules.{key} must be a list")
    if "max_input_chars" in rules and int(rules["max_input_chars"]) <= 0:
        raise ValueError("rules.max_input_chars must be positive")
    if "min_input_chars" in rules and int(rules["min_input_chars"]) < 0:
        raise ValueError("rules.min_input_chars must be >= 0")


def _validate_slot_policies(slot_policies: dict[str, Any]) -> None:
    if not slot_policies:
        return
    if not isinstance(slot_policies, dict):
        raise ValueError("slot_policies must be object")
    for key in ("default", "scenes"):
        if key in slot_policies and not isinstance(slot_policies[key], dict):
            raise ValueError(f"slot_policies.{key} must be object")
