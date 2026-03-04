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
    """配置总校验入口，启动阶段失败优先。"""
    _validate_capabilities(config.capabilities)
    _validate_scene_config(config.scenes)
    _validate_template_config(config.templates, config.scenes)
    _validate_seed_cases(config.seed_cases, config.scenes)
    _validate_thresholds(config.thresholds)
    _validate_vector(config.vector)
    _validate_rules(config.rules)
    _validate_slot_policies(config.slot_policies)


def _validate_capabilities(capabilities: list[dict[str, Any]]) -> None:
    """校验 capability 主体结构及嵌套 intent/template 合法性。"""
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
        if "flow_type" in cap:
            flow_type = str(cap.get("flow_type", "")).strip().lower()
            if flow_type and flow_type not in {"query", "report", "direct", "unknown"}:
                raise ValueError(f"Capability flow_type invalid: {capability_id}.{flow_type}")
        if "router_priority" in cap:
            try:
                int(cap["router_priority"])
            except (TypeError, ValueError):
                raise ValueError(f"Capability router_priority must be int: {capability_id}")
        if "entry_phrases" in cap and not isinstance(cap["entry_phrases"], list):
            raise ValueError(f"Capability entry_phrases must be list: {capability_id}")
        if "clarify" in cap and not isinstance(cap["clarify"], dict):
            raise ValueError(f"Capability clarify must be object: {capability_id}")
        if "llm_assist" in cap and not isinstance(cap["llm_assist"], dict):
            raise ValueError(f"Capability llm_assist must be object: {capability_id}")
        if "execution" in cap and not isinstance(cap["execution"], dict):
            raise ValueError(f"Capability execution must be object: {capability_id}")

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
    """校验 scenes 视图结构。"""
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
    """校验 templates 视图结构及 scene 引用。"""
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
    """校验 seed cases 视图结构及 scene 引用。"""
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
    """校验 capability.intents 的语义最小集与字段类型。"""
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
    """校验单条 intent 内联模板定义。"""
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
    """阈值校验：统一要求 [0,1]。"""
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
    """向量与预提参配置校验。"""
    vector_missing = REQUIRED_VECTOR_KEYS - set(vector.keys())
    if vector_missing:
        raise ValueError(f"Vector config missing keys: {vector_missing}")
    if (
        vector["scene_topk"] <= 0
        or vector["template_topk"] <= 0
        or vector["seed_case_topk"] <= 0
    ):
        raise ValueError("scene_topk/template_topk/seed_case_topk must be positive")
    if "query_vector_cache_size" in vector and int(vector["query_vector_cache_size"]) < 1:
        raise ValueError("query_vector_cache_size must be >= 1")
    search_backend = vector.get("search_backend", "opensearch")
    if str(search_backend).lower() not in {"opensearch", "elasticsearch", "es"}:
        raise ValueError(
            "vector.search_backend must be one of: opensearch, elasticsearch, es"
        )
    _validate_embedding_config(vector)
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


def _validate_embedding_config(vector: dict[str, Any]) -> None:
    """embedding provider 配置校验，兼容旧 model_name/device 配置。"""
    embedding = vector.get("embedding")
    if embedding is not None and not isinstance(embedding, dict):
        raise ValueError("vector.embedding must be object")
    cfg = embedding if isinstance(embedding, dict) else {}

    provider = str(cfg.get("provider", "sentence_transformers")).strip().lower()
    if provider not in {"sentence_transformers", "e5", "hf_st", "openai_embedding", "openai_compatible"}:
        raise ValueError(
            "vector.embedding.provider must be one of: "
            "sentence_transformers, e5, hf_st, openai_embedding, openai_compatible"
        )

    # 兼容旧字段 model_name/device。
    model = str(cfg.get("model", vector.get("model_name", ""))).strip()
    if not model:
        raise ValueError("vector.embedding.model is required (or legacy vector.model_name)")

    if "dimension" in cfg and int(cfg["dimension"]) < 1:
        raise ValueError("vector.embedding.dimension must be >= 1")
    if "timeout_ms" in cfg and int(cfg["timeout_ms"]) < 100:
        raise ValueError("vector.embedding.timeout_ms must be >= 100")

    for key in ("query_prefix", "passage_prefix", "endpoint_path", "base_url", "api_key_env"):
        if key in cfg and not isinstance(cfg[key], str):
            raise ValueError(f"vector.embedding.{key} must be str")

    for key in ("normalize_embeddings",):
        if key in cfg and not isinstance(cfg[key], bool):
            raise ValueError(f"vector.embedding.{key} must be bool")

    for key in ("request_extra",):
        if key in cfg and not isinstance(cfg[key], dict):
            raise ValueError(f"vector.embedding.{key} must be object")

    for key in ("input_field", "model_field", "response_data_field", "response_vector_field"):
        if key in cfg and not isinstance(cfg[key], str):
            raise ValueError(f"vector.embedding.{key} must be str")

    if provider in {"openai_embedding", "openai_compatible"}:
        if "base_url" in cfg and not str(cfg.get("base_url", "")).strip():
            raise ValueError("vector.embedding.base_url must not be empty for openai_compatible")
        if int(cfg.get("dimension", 0) or 0) < 1:
            raise ValueError(
                "vector.embedding.dimension must be configured for openai_compatible provider"
            )


def _validate_rules(rules: dict[str, Any]) -> None:
    """规则配置基础校验。"""
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

    flow_router = rules.get("flow_router")
    if flow_router is not None:
        if not isinstance(flow_router, dict):
            raise ValueError("rules.flow_router must be object")
        if "enabled" in flow_router and not isinstance(flow_router["enabled"], bool):
            raise ValueError("rules.flow_router.enabled must be bool")
        if "min_confidence" in flow_router and not (0 <= float(flow_router["min_confidence"]) <= 1):
            raise ValueError("rules.flow_router.min_confidence must be in [0,1]")
        if "ambiguous_gap" in flow_router and not (0 <= float(flow_router["ambiguous_gap"]) <= 1):
            raise ValueError("rules.flow_router.ambiguous_gap must be in [0,1]")
        if "llm_on_low_confidence" in flow_router and not isinstance(
            flow_router["llm_on_low_confidence"], bool
        ):
            raise ValueError("rules.flow_router.llm_on_low_confidence must be bool")
        if "allow_direct_pass" in flow_router and not isinstance(flow_router["allow_direct_pass"], bool):
            raise ValueError("rules.flow_router.allow_direct_pass must be bool")
        if "direct_pass_intents" in flow_router and not isinstance(
            flow_router["direct_pass_intents"], list
        ):
            raise ValueError("rules.flow_router.direct_pass_intents must be list")

    llm = rules.get("llm")
    if llm is not None:
        if not isinstance(llm, dict):
            raise ValueError("rules.llm must be object")
        if "enabled" in llm and not isinstance(llm["enabled"], bool):
            raise ValueError("rules.llm.enabled must be bool")
        if "max_calls_per_request" in llm and int(llm["max_calls_per_request"]) < 1:
            raise ValueError("rules.llm.max_calls_per_request must be >=1")
        if "timeout_ms" in llm and int(llm["timeout_ms"]) < 100:
            raise ValueError("rules.llm.timeout_ms must be >=100")
        if "max_input_chars" in llm and int(llm["max_input_chars"]) < 20:
            raise ValueError("rules.llm.max_input_chars must be >=20")
        if "max_output_tokens" in llm and int(llm["max_output_tokens"]) < 16:
            raise ValueError("rules.llm.max_output_tokens must be >=16")
        if "enable_thinking" in llm and not isinstance(llm["enable_thinking"], bool):
            raise ValueError("rules.llm.enable_thinking must be bool")
        if "response_format_json" in llm and not isinstance(llm["response_format_json"], bool):
            raise ValueError("rules.llm.response_format_json must be bool")
        if "provider" in llm and str(llm["provider"]).strip().lower() not in {"openai_compatible"}:
            raise ValueError("rules.llm.provider currently supports: openai_compatible")
        for key in (
            "api_key_env",
            "base_url_env",
            "model_env",
            "endpoint_path",
            "api_key_header",
            "api_key_prefix",
            "model_field",
            "messages_field",
            "max_tokens_field",
        ):
            if key in llm and not isinstance(llm[key], str):
                raise ValueError(f"rules.llm.{key} must be str")
        if "request_extra" in llm and not isinstance(llm["request_extra"], dict):
            raise ValueError("rules.llm.request_extra must be object")
        if "response_content_path" in llm and not isinstance(
            llm["response_content_path"], (list, str)
        ):
            raise ValueError("rules.llm.response_content_path must be list or str")

    clarify = rules.get("clarify")
    if clarify is not None:
        if not isinstance(clarify, dict):
            raise ValueError("rules.clarify must be object")
        if "global_max_rounds" in clarify and int(clarify["global_max_rounds"]) < 1:
            raise ValueError("rules.clarify.global_max_rounds must be >=1")


def _validate_slot_policies(slot_policies: dict[str, Any]) -> None:
    """槽位策略配置基础校验。"""
    if not slot_policies:
        return
    if not isinstance(slot_policies, dict):
        raise ValueError("slot_policies must be object")
    for key in ("default", "scenes"):
        if key in slot_policies and not isinstance(slot_policies[key], dict):
            raise ValueError(f"slot_policies.{key} must be object")
