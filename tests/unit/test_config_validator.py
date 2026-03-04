from __future__ import annotations

import copy

import pytest

from chat_pre_check.infrastructure.config.loader import AppConfig, load_app_config
from chat_pre_check.infrastructure.config.validator import validate_config


def _clone_config(config: AppConfig) -> AppConfig:
    return AppConfig(
        capabilities=copy.deepcopy(config.capabilities),
        scenes=copy.deepcopy(config.scenes),
        templates=copy.deepcopy(config.templates),
        cases=copy.deepcopy(config.cases),
        seed_cases=copy.deepcopy(config.seed_cases),
        rules=copy.deepcopy(config.rules),
        thresholds=copy.deepcopy(config.thresholds),
        vector=copy.deepcopy(config.vector),
        slot_policies=copy.deepcopy(config.slot_policies),
    )


def test_validator_rejects_non_positive_query_vector_cache_size() -> None:
    config = _clone_config(load_app_config("configs"))
    config.vector["query_vector_cache_size"] = 0
    with pytest.raises(ValueError, match="query_vector_cache_size"):
        validate_config(config)


def test_validator_rejects_unknown_search_backend() -> None:
    config = _clone_config(load_app_config("configs"))
    config.vector["search_backend"] = "unknown_backend"
    with pytest.raises(ValueError, match="search_backend"):
        validate_config(config)


def test_validator_accepts_es_alias_search_backend() -> None:
    config = _clone_config(load_app_config("configs"))
    config.vector["search_backend"] = "es"
    validate_config(config)


def test_validator_rejects_intent_without_text_label_and_examples() -> None:
    config = _clone_config(load_app_config("configs"))
    config.capabilities[0]["intents"] = [
        {
            "case_id": "invalid_intent_empty_semantics",
            "template": {
                "template_id": "tpl_invalid_intent",
                "slot_schema": {"required": [], "optional": []},
            },
        }
    ]
    with pytest.raises(ValueError, match="text/label/examples"):
        validate_config(config)


def test_validator_rejects_invalid_flow_type() -> None:
    config = _clone_config(load_app_config("configs"))
    config.capabilities[0]["flow_type"] = "invalid_flow"
    with pytest.raises(ValueError, match="flow_type"):
        validate_config(config)


def test_validator_rejects_invalid_llm_timeout() -> None:
    config = _clone_config(load_app_config("configs"))
    config.rules["llm"]["timeout_ms"] = 10
    with pytest.raises(ValueError, match="timeout_ms"):
        validate_config(config)


def test_validator_rejects_invalid_llm_response_format_flag() -> None:
    config = _clone_config(load_app_config("configs"))
    config.rules["llm"]["response_format_json"] = "yes"
    with pytest.raises(ValueError, match="response_format_json"):
        validate_config(config)


def test_validator_rejects_invalid_flow_router_llm_low_confidence_flag() -> None:
    config = _clone_config(load_app_config("configs"))
    config.rules["flow_router"]["llm_on_low_confidence"] = "yes"
    with pytest.raises(ValueError, match="llm_on_low_confidence"):
        validate_config(config)


def test_validator_rejects_invalid_embedding_provider() -> None:
    config = _clone_config(load_app_config("configs"))
    config.vector["embedding"]["provider"] = "unknown_provider"
    with pytest.raises(ValueError, match="embedding.provider"):
        validate_config(config)


def test_validator_rejects_openai_embedding_without_dimension() -> None:
    config = _clone_config(load_app_config("configs"))
    config.vector["embedding"]["provider"] = "openai_compatible"
    config.vector["embedding"]["base_url"] = "https://example.com/v1"
    config.vector["embedding"]["dimension"] = 0
    with pytest.raises(ValueError, match="embedding.dimension"):
        validate_config(config)


def test_validator_rejects_invalid_llm_response_content_path() -> None:
    config = _clone_config(load_app_config("configs"))
    config.rules["llm"]["response_content_path"] = {"a": 1}
    with pytest.raises(ValueError, match="response_content_path"):
        validate_config(config)
