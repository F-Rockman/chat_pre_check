from __future__ import annotations

import json

import pytest

from template_capability.config import TemplateConfig, load_template_config
from template_capability.engine import TemplateCapabilityEngine
from template_capability.models import MatcherSettings, SlotExtractorDefinition, TemplateDefinition, TextMatchRule
from template_capability.scoring import constraint_score, has_negative_term
from template_capability.text_matching import match_text_rule


def test_match_text_rule_supports_substring_whole_word_and_exact():
    assert match_text_rule("device idc 告警", TextMatchRule(term="idc"))
    assert match_text_rule("device idc 告警", TextMatchRule(term="idc", match_mode="whole_word"))
    assert not match_text_rule("deviceidc1 告警", TextMatchRule(term="idc", match_mode="whole_word"))
    assert match_text_rule("分析", TextMatchRule(term="分析", match_mode="exact"))
    assert not match_text_rule("分析告警数量", TextMatchRule(term="分析", match_mode="exact"))


def test_blocked_terms_keep_old_string_behavior():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.58,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={"lexical": 1.0},
                blocked_terms=["分析"],
            ),
            templates=[],
        )
    )

    payload = engine.match("帮我分析设备告警").to_dict()

    assert payload["status"] == "unmatched"
    assert payload["trace"]["blocked_term"] == "分析"


def test_blocked_terms_whole_word_avoids_false_positive_inside_token():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.2,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={"lexical": 1.0},
                blocked_terms=[{"term": "idc", "match_mode": "whole_word"}],
            ),
            templates=[
                TemplateDefinition(
                    template_id="device.generic.count",
                    query_mode="metric_query",
                    description="查询设备数量",
                    utterances=["查询设备数量"],
                    required_slots=[],
                    optional_slots=[],
                    must_terms=[["设备"], ["数量"]],
                    negative_terms=[],
                    slot_constraints={},
                )
            ],
        )
    )

    matched_payload = engine.match("查询deviceidc1设备数量").to_dict()
    blocked_payload = engine.match("查询 idc 设备数量").to_dict()

    assert matched_payload["template_id"] == "device.generic.count"
    assert blocked_payload["template_id"] == -1
    assert blocked_payload["trace"]["blocked_term"] == "idc"


def test_must_terms_whole_word_is_more_precise_than_substring():
    template = TemplateDefinition(
        template_id="device.idc.count",
        query_mode="metric_query",
        description="查询 idc 设备数量",
        utterances=["查询 idc 设备数量"],
        required_slots=[],
        optional_slots=[],
        must_terms=[
            [{"term": "idc", "match_mode": "whole_word"}],
            ["设备"],
            ["数量"],
        ],
        negative_terms=[],
        slot_constraints={},
    )

    whole_word_score = constraint_score(template, "查询 idc 设备数量", {})
    false_positive_score = constraint_score(template, "查询 deviceidc1 设备数量", {})

    assert whole_word_score > false_positive_score
    assert false_positive_score < 1.0


def test_negative_terms_exact_only_blocks_full_exact_text():
    template = TemplateDefinition(
        template_id="device.count",
        query_mode="metric_query",
        description="查询设备数量",
        utterances=["查询设备数量"],
        required_slots=[],
        optional_slots=[],
        must_terms=[],
        negative_terms=[{"term": "分析", "match_mode": "exact"}],
        slot_constraints={},
    )

    assert has_negative_term(template, "分析")
    assert not has_negative_term(template, "分析设备数量")


def test_invalid_match_mode_fails_fast_in_config(tmp_path):
    path = tmp_path / "bad_match_mode.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {
                    "blocked_terms": [
                        {"term": "idc", "match_mode": "regex"}
                    ]
                },
                "templates": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="unsupported match_mode 'regex'"):
        load_template_config(path)


def test_object_style_term_rules_load_from_config(tmp_path):
    path = tmp_path / "term_rules.json"
    path.write_text(
        json.dumps(
            {
                "matcher": {
                    "blocked_terms": [
                        {"term": "idc", "match_mode": "whole_word"}
                    ]
                },
                "templates": [
                    {
                        "template_id": "device.idc.count",
                        "query_mode": "metric_query",
                        "description": "查询 idc 设备数量",
                        "utterances": ["查询 idc 设备数量"],
                        "required_slots": [],
                        "optional_slots": [],
                        "must_terms": [
                            [
                                {"term": "idc", "match_mode": "whole_word"}
                            ]
                        ],
                        "negative_terms": [
                            {"term": "分析", "match_mode": "exact"}
                        ],
                        "slot_constraints": {},
                        "slot_extractors": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_template_config(path)

    assert config.settings.blocked_terms[0].match_mode == "whole_word"
    assert config.templates[0].must_terms[0][0].match_mode == "whole_word"
    assert config.templates[0].negative_terms[0].match_mode == "exact"
