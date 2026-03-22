from __future__ import annotations

import json

import pytest

from template_capability.config import load_template_config
from template_capability.validation import TemplateConfigValidationError


def test_duplicate_template_ids_fail_fast(tmp_path):
    path = tmp_path / "bad_templates.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {"template_id": "dup.demo", "query_mode": "metric_query", "description": "", "utterances": [], "required_slots": [], "optional_slots": [], "must_terms": [], "negative_terms": [], "slot_constraints": {}, "slot_extractors": {}},
                    {"template_id": "dup.demo", "query_mode": "metric_query", "description": "", "utterances": [], "required_slots": [], "optional_slots": [], "must_terms": [], "negative_terms": [], "slot_constraints": {}, "slot_extractors": {}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="duplicate template_id detected: dup.demo"):
        load_template_config(path)


def test_unknown_extractor_type_fails_fast(tmp_path):
    path = tmp_path / "bad_extractor.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {
                        "template_id": "bad.extractor",
                        "query_mode": "metric_query",
                        "description": "",
                        "utterances": [],
                        "required_slots": [],
                        "optional_slots": [],
                        "must_terms": [],
                        "negative_terms": [],
                        "slot_constraints": {},
                        "slot_extractors": {
                            "cpu_threshold": {
                                "extractors": [
                                    {
                                        "type": "python_code",
                                        "code": "return 80"
                                    }
                                ]
                            }
                        }
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="unsupported extractor type 'python_code'"):
        load_template_config(path)


def test_invalid_regex_fails_fast(tmp_path):
    path = tmp_path / "bad_regex.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {
                        "template_id": "bad.regex",
                        "query_mode": "metric_query",
                        "description": "",
                        "utterances": [],
                        "required_slots": ["cpu_threshold"],
                        "optional_slots": [],
                        "must_terms": [],
                        "negative_terms": [],
                        "slot_constraints": {},
                        "slot_extractors": {
                            "cpu_threshold": {
                                "extractors": [
                                    {
                                        "type": "regex",
                                        "patterns": [
                                            {
                                                "pattern": "(cpu",
                                                "group": 1,
                                                "value_type": "int"
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="invalid regex"):
        load_template_config(path)


def test_required_slot_without_fill_path_fails_fast(tmp_path):
    path = tmp_path / "missing_fill_path.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {
                        "template_id": "missing.slot",
                        "query_mode": "metric_query",
                        "description": "",
                        "utterances": [],
                        "required_slots": ["query_operator"],
                        "optional_slots": [],
                        "must_terms": [],
                        "negative_terms": [],
                        "slot_constraints": {},
                        "slot_extractors": {},
                        "llm_slot_extraction": {
                            "enabled": False,
                            "slots": []
                        }
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="requires slot 'query_operator'"):
        load_template_config(path)


def test_optional_slot_without_fill_path_fails_fast(tmp_path):
    path = tmp_path / "missing_optional_fill_path.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {
                        "template_id": "missing.optional.slot",
                        "query_mode": "metric_query",
                        "description": "",
                        "utterances": [],
                        "required_slots": [],
                        "optional_slots": ["region_id"],
                        "must_terms": [],
                        "negative_terms": [],
                        "slot_constraints": {},
                        "slot_extractors": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="declares optional slot 'region_id'"):
        load_template_config(path)


def test_slot_constraint_without_fill_path_fails_fast(tmp_path):
    path = tmp_path / "missing_constraint_fill_path.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {
                        "template_id": "missing.constraint.slot",
                        "query_mode": "metric_query",
                        "description": "",
                        "utterances": [],
                        "required_slots": [],
                        "optional_slots": [],
                        "must_terms": [],
                        "negative_terms": [],
                        "slot_constraints": {
                            "query_operator": ["count"]
                        },
                        "slot_extractors": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="constrains slot 'query_operator'"):
        load_template_config(path)


def test_required_one_of_group_requires_at_least_two_slots(tmp_path):
    path = tmp_path / "bad_required_one_of.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {
                        "template_id": "bad.required_one_of",
                        "query_mode": "metric_query",
                        "description": "",
                        "utterances": [],
                        "required_slots": [],
                        "optional_slots": [],
                        "must_terms": [],
                        "negative_terms": [],
                        "slot_constraints": {},
                        "required_one_of": [["selector_name"]],
                        "slot_extractors": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="required_one_of\\[1\\] must contain at least 2 slots"):
        load_template_config(path)


def test_conditional_required_must_declare_trigger(tmp_path):
    path = tmp_path / "bad_conditional_required.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {},
                "templates": [
                    {
                        "template_id": "bad.conditional_required",
                        "query_mode": "metric_query",
                        "description": "",
                        "utterances": [],
                        "required_slots": [],
                        "optional_slots": [],
                        "must_terms": [],
                        "negative_terms": [],
                        "slot_constraints": {},
                        "conditional_required": [
                            {
                                "require": ["selector_value"]
                            }
                        ],
                        "slot_extractors": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="conditional_required\\[1\\] must declare when_any or when_all"):
        load_template_config(path)


def test_remote_vector_provider_requires_connection_fields(tmp_path):
    path = tmp_path / "bad_remote_vector.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {
                    "vector": {
                        "provider": "remote",
                        "dimension": 512
                    }
                },
                "templates": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="matcher.vector.remote requires base_url"):
        load_template_config(path)


def test_remote_reranker_provider_requires_connection_fields(tmp_path):
    path = tmp_path / "bad_remote_reranker.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {
                    "reranker": {
                        "enabled": True,
                        "provider": "openai_compatible",
                        "top_k": 10,
                    }
                },
                "templates": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateConfigValidationError, match="matcher.reranker.remote requires base_url"):
        load_template_config(path)
