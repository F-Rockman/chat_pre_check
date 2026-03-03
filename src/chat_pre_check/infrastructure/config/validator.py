from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chat_pre_check.infrastructure.config.loader import AppConfig


REQUIRED_SCENE_KEYS = {"scene_id", "description", "required_slots", "defaults"}
REQUIRED_TEMPLATE_KEYS = {"template_id", "scene_id", "slot_schema", "examples"}
REQUIRED_CAPABILITY_KEYS = {"capability_id", "description", "scope", "slots"}
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
    _validate_capabilities(config.capabilities)
    _validate_scene_config(config.scenes)
    _validate_template_config(config.templates, config.scenes)
    _validate_seed_cases(config.seed_cases, config.scenes)
    _validate_thresholds(config.thresholds)
    _validate_vector(config.vector)
    _validate_rules(config.rules)
    _validate_slot_policies(config.slot_policies)


def _validate_capabilities(capabilities: list[dict[str, Any]]) -> None:
    capability_ids = set()
    for cap in capabilities:
        missing = REQUIRED_CAPABILITY_KEYS - set(cap.keys())
        if missing:
            raise ValueError(f"Capability config missing keys: {missing}")
        capability_id = str(cap.get("capability_id", "")).strip()
        if not capability_id:
            raise ValueError("capability_id must not be empty")
        if capability_id in capability_ids:
            raise ValueError(f"Duplicate capability_id detected: {capability_id}")
        capability_ids.add(capability_id)

        scope = cap.get("scope", {})
        if not isinstance(scope, dict):
            raise ValueError(f"Capability scope must be object: {capability_id}")
        if "keywords" in scope and not isinstance(scope["keywords"], list):
            raise ValueError(f"Capability scope.keywords must be list: {capability_id}")
        if "examples" in scope and not isinstance(scope["examples"], list):
            raise ValueError(f"Capability scope.examples must be list: {capability_id}")

        slots = cap.get("slots", {})
        if not isinstance(slots, dict):
            raise ValueError(f"Capability slots must be object: {capability_id}")
        if "required" in slots and not isinstance(slots["required"], list):
            raise ValueError(f"Capability slots.required must be list: {capability_id}")
        if "conditional" in slots and not isinstance(slots["conditional"], list):
            raise ValueError(f"Capability slots.conditional must be list: {capability_id}")
        if "defaults" in slots and not isinstance(slots["defaults"], dict):
            raise ValueError(f"Capability slots.defaults must be object: {capability_id}")
        if "clarify_policy" in slots and not isinstance(slots["clarify_policy"], dict):
            raise ValueError(f"Capability slots.clarify_policy must be object: {capability_id}")

        templates = cap.get("templates", [])
        if templates is not None and not isinstance(templates, list):
            raise ValueError(f"Capability templates must be list: {capability_id}")
        recommendations = cap.get("recommendations", [])
        if recommendations is not None and not isinstance(recommendations, list):
            raise ValueError(f"Capability recommendations must be list: {capability_id}")
        seed_cases = cap.get("seed_cases", [])
        if seed_cases is not None and not isinstance(seed_cases, list):
            raise ValueError(f"Capability seed_cases must be list: {capability_id}")
        intents = cap.get("intents", [])
        if intents is not None and not isinstance(intents, list):
            raise ValueError(f"Capability intents must be list: {capability_id}")
        _validate_capability_intents(capability_id, intents)
        slot_policy = cap.get("slot_policy", {})
        if slot_policy is not None and not isinstance(slot_policy, dict):
            raise ValueError(f"Capability slot_policy must be object: {capability_id}")


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


def _validate_seed_cases(seed_cases: list[dict[str, Any]], scenes: list[dict[str, Any]]) -> None:
    scene_ids = {scene["scene_id"] for scene in scenes}
    case_ids = set()
    for case in seed_cases:
        case_id = str(case.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("Seed case missing case_id")
        if case_id in case_ids:
            raise ValueError(f"Duplicate seed case_id detected: {case_id}")
        case_ids.add(case_id)
        scene_id = str(case.get("scene_id", "")).strip()
        if not scene_id or scene_id not in scene_ids:
            raise ValueError(f"Seed case scene_id not found: {case_id} -> {scene_id}")
        text = str(case.get("text", "")).strip()
        if len(text) < 2:
            raise ValueError(f"Seed case text too short: {case_id}")


def _validate_capability_intents(capability_id: str, intents: Any) -> None:
    if intents in (None, []):
        return
    if not isinstance(intents, list):
        raise ValueError(f"Capability intents must be list: {capability_id}")
    seen_case_ids: set[str] = set()
    seen_template_ids: set[str] = set()
    for idx, intent in enumerate(intents, start=1):
        if not isinstance(intent, dict):
            raise ValueError(f"Capability intent item must be object: {capability_id}[{idx}]")

        case_id = str(intent.get("case_id", "")).strip()
        if not case_id:
            raise ValueError(f"Capability intent missing case_id: {capability_id}[{idx}]")
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate intent case_id in capability: {capability_id}.{case_id}")
        seen_case_ids.add(case_id)

        text = str(intent.get("text", "")).strip()
        label = str(intent.get("label", "")).strip()
        examples = intent.get("examples", [])
        if examples is not None and not isinstance(examples, list):
            raise ValueError(f"Capability intent examples must be list: {capability_id}.{case_id}")
        has_examples = isinstance(examples, list) and any(str(item).strip() for item in examples)
        if not text and not label and not has_examples:
            raise ValueError(f"Capability intent needs text/label/examples: {capability_id}.{case_id}")
        if text and len(text) < 2:
            raise ValueError(f"Capability intent text too short: {capability_id}.{case_id}")

        if "keywords" in intent and not isinstance(intent["keywords"], list):
            raise ValueError(f"Capability intent keywords must be list: {capability_id}.{case_id}")
        if "examples" in intent and not isinstance(intent["examples"], list):
            raise ValueError(f"Capability intent examples must be list: {capability_id}.{case_id}")
        if "negative_keywords" in intent and not isinstance(intent["negative_keywords"], list):
            raise ValueError(
                f"Capability intent negative_keywords must be list: {capability_id}.{case_id}"
            )
        if "enabled" in intent and not isinstance(intent["enabled"], bool):
            raise ValueError(f"Capability intent enabled must be bool: {capability_id}.{case_id}")
        if "tags" in intent and not isinstance(intent["tags"], list):
            raise ValueError(f"Capability intent tags must be list: {capability_id}.{case_id}")
        if "slots" in intent and not isinstance(intent["slots"], dict):
            raise ValueError(f"Capability intent slots must be object: {capability_id}.{case_id}")

        template = intent.get("template")
        root_template_id = str(intent.get("template_id", "")).strip()
        if template is not None and not isinstance(template, dict):
            raise ValueError(f"Capability intent template must be object: {capability_id}.{case_id}")

        if isinstance(template, dict):
            _validate_intent_template(
                capability_id=capability_id,
                case_id=case_id,
                template=template,
                seen_template_ids=seen_template_ids,
            )
        elif root_template_id:
            _validate_intent_template(
                capability_id=capability_id,
                case_id=case_id,
                template={
                    "template_id": root_template_id,
                    "slot_schema": intent.get("slot_schema", {}),
                },
                seen_template_ids=seen_template_ids,
            )


def _validate_intent_template(
    *,
    capability_id: str,
    case_id: str,
    template: dict[str, Any],
    seen_template_ids: set[str],
) -> None:
    template_id = str(template.get("template_id", "")).strip()
    if not template_id:
        raise ValueError(
            f"Capability intent template_id must not be empty: {capability_id}.{case_id}"
        )
    if template_id in seen_template_ids:
        raise ValueError(f"Duplicate intent template_id in capability: {capability_id}.{template_id}")
    seen_template_ids.add(template_id)

    slot_schema = template.get("slot_schema", {})
    if not isinstance(slot_schema, dict):
        raise ValueError(
            f"Capability intent template slot_schema must be object: {capability_id}.{case_id}"
        )
    required = slot_schema.get("required", [])
    optional = slot_schema.get("optional", [])
    if not isinstance(required, list):
        raise ValueError(
            f"Capability intent template slot_schema.required must be list: {capability_id}.{case_id}"
        )
    if not isinstance(optional, list):
        raise ValueError(
            f"Capability intent template slot_schema.optional must be list: {capability_id}.{case_id}"
        )


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

    prefill = vector.get("param_prefill")
    if prefill is None:
        return
    if not isinstance(prefill, dict):
        raise ValueError("param_prefill must be object")
    if "enabled" in prefill and not isinstance(prefill["enabled"], bool):
        raise ValueError("param_prefill.enabled must be bool")
    if "auto_commit" in prefill and not isinstance(prefill["auto_commit"], bool):
        raise ValueError("param_prefill.auto_commit must be bool")
    if (
        "skip_remote_resolver_when_prefilled" in prefill
        and not isinstance(prefill["skip_remote_resolver_when_prefilled"], bool)
    ):
        raise ValueError("param_prefill.skip_remote_resolver_when_prefilled must be bool")
    if "dictionary_file" in prefill and not isinstance(prefill["dictionary_file"], str):
        raise ValueError("param_prefill.dictionary_file must be str")
    if "commit_score" in prefill and not (0 <= float(prefill["commit_score"]) <= 1):
        raise ValueError("param_prefill.commit_score must be in [0,1]")
    if "min_gap" in prefill and not (0 <= float(prefill["min_gap"]) <= 1):
        raise ValueError("param_prefill.min_gap must be in [0,1]")
    if "max_candidates_per_slot" in prefill and int(prefill["max_candidates_per_slot"]) < 1:
        raise ValueError("param_prefill.max_candidates_per_slot must be >= 1")
    if "ignore_case" in prefill and not isinstance(prefill["ignore_case"], bool):
        raise ValueError("param_prefill.ignore_case must be bool")
    if "default_word_boundary" in prefill and not isinstance(
        prefill["default_word_boundary"], bool
    ):
        raise ValueError("param_prefill.default_word_boundary must be bool")
    if "min_term_length" in prefill and int(prefill["min_term_length"]) < 1:
        raise ValueError("param_prefill.min_term_length must be >= 1")
    if "max_matches" in prefill and int(prefill["max_matches"]) < 1:
        raise ValueError("param_prefill.max_matches must be >= 1")
    if "domain_penalty" in prefill and float(prefill["domain_penalty"]) < 0:
        raise ValueError("param_prefill.domain_penalty must be >= 0")
    if "domain_priority" in prefill and not isinstance(prefill["domain_priority"], dict):
        raise ValueError("param_prefill.domain_priority must be object")
    if "slot_domain_priority" in prefill and not isinstance(
        prefill["slot_domain_priority"], dict
    ):
        raise ValueError("param_prefill.slot_domain_priority must be object")

    domain_router = prefill.get("domain_router")
    if domain_router is not None:
        if not isinstance(domain_router, dict):
            raise ValueError("param_prefill.domain_router must be object")
        if "enabled" in domain_router and not isinstance(domain_router["enabled"], bool):
            raise ValueError("param_prefill.domain_router.enabled must be bool")
        if "max_domains" in domain_router and int(domain_router["max_domains"]) < 1:
            raise ValueError("param_prefill.domain_router.max_domains must be >= 1")
        if "default_domains" in domain_router and not isinstance(
            domain_router["default_domains"], list
        ):
            raise ValueError("param_prefill.domain_router.default_domains must be list")
        for key in ("scene_domains", "keyword_domains", "slot_domains"):
            if key in domain_router and not isinstance(domain_router[key], dict):
                raise ValueError(f"param_prefill.domain_router.{key} must be object")


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
