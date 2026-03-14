from __future__ import annotations

import json

from template_capability.config import TemplateConfig
from template_capability.engine import TemplateCapabilityEngine
from template_capability.models import (
    MatcherSettings,
    QueryRewriteRule,
    QueryRewriteSettings,
    TemplateDefinition,
)
from template_capability.rewrite import QueryRewriteStateMachine


def test_query_rewrite_state_machine_prefers_longest_match():
    rewriter = QueryRewriteStateMachine(
        QueryRewriteSettings(
            enabled=True,
            max_passes=1,
            rules=[
                QueryRewriteRule(rule_id="vendor.short", source="思科", target="cisco"),
                QueryRewriteRule(rule_id="vendor.full", source="思科设备", target="cisic"),
            ],
        )
    )

    payload = rewriter.rewrite("查询思科设备的告警")

    assert payload.rewritten_text == "查询cisic的告警"
    assert payload.changed is True
    assert payload.hits[0].rule_id == "vendor.full"


def test_query_rewrite_state_machine_supports_multi_pass_rewrite():
    rewriter = QueryRewriteStateMachine(
        QueryRewriteSettings(
            enabled=True,
            max_passes=3,
            rules=[
                QueryRewriteRule(rule_id="school.short", source="北二小", target="北京第二小学"),
                QueryRewriteRule(rule_id="school.alias", source="北京第二小学", target="北京市第二小学"),
            ],
        )
    )

    payload = rewriter.rewrite("查询北二小的告警")

    assert payload.rewritten_text == "查询北京市第二小学的告警"
    assert payload.pass_count == 2
    assert [item.rule_id for item in payload.hits] == ["school.short", "school.alias"]


def test_engine_applies_query_rewrite_before_matching():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.4,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.6,
                    "sample": 0.1,
                    "vector": 0.1,
                    "fusion": 0.1,
                    "slot_fit": 0.05,
                    "constraint": 0.05,
                    "structure": 0.0,
                },
            ),
            query_rewrite=QueryRewriteSettings(
                enabled=True,
                max_passes=1,
                rules=[
                    QueryRewriteRule(
                        rule_id="school.short",
                        source="北二小",
                        target="北京第二小学",
                    )
                ],
            ),
            templates=[
                TemplateDefinition(
                    template_id="school.alarm.count",
                    query_mode="metric_query",
                    description="查询北京第二小学告警数量",
                    utterances=["查询北京第二小学的告警数量"],
                    required_slots=[],
                    optional_slots=[],
                    must_terms=[["北京第二小学"], ["告警"]],
                    negative_terms=[],
                    slot_constraints={},
                )
            ],
        )
    )

    payload = engine.match("查询北二小的告警").to_dict()

    assert payload["template_id"] == "school.alarm.count"
    assert payload["trace"]["rewrite_trace"]["changed"] is True
    assert payload["trace"]["rewrite_trace"]["rewritten_text"] == "查询北京第二小学的告警"


def test_query_rewrite_whole_word_does_not_replace_inside_larger_token():
    rewriter = QueryRewriteStateMachine(
        QueryRewriteSettings(
            enabled=True,
            max_passes=1,
            rules=[
                QueryRewriteRule(rule_id="cpu.typo", source="cup", target="cpu", match_mode="whole_word"),
            ],
        )
    )

    payload = rewriter.rewrite("查询cup和occupancy的告警")

    assert payload.rewritten_text == "查询cpu和occupancy的告警"
    assert len(payload.hits) == 1


def test_query_rewrite_can_hot_reload_external_dictionary(tmp_path):
    dictionary_path = tmp_path / "rewrite_rules.json"
    dictionary_path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "rule_id": "school.short",
                        "source": "北二小",
                        "target": "北京第二小学",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rewriter = QueryRewriteStateMachine(
        QueryRewriteSettings(
            enabled=True,
            max_passes=2,
            dictionary_path=str(dictionary_path),
            reload_on_change=True,
        )
    )

    first = rewriter.rewrite("查询北二小的告警")
    assert first.rewritten_text == "查询北京第二小学的告警"

    dictionary_path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "rule_id": "school.short",
                        "source": "北二小",
                        "target": "北京市第二小学",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    second = rewriter.rewrite("查询北二小的告警")
    assert second.rewritten_text == "查询北京市第二小学的告警"
