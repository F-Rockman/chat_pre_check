from __future__ import annotations

from template_capability.config import TemplateConfig
from template_capability.engine import TemplateCapabilityEngine
from template_capability.fallback import SlotFallbackSuggestion
from template_capability.models import (
    ConditionalSlotRequirement,
    MatchStatus,
    MatcherSettings,
    SlotExtractorDefinition,
    SlotGroupRequirement,
    TemplateDefinition,
)


class StubTemplateSlotResolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve_slots(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        current_slots: dict[str, object],
        missing_slots: list[str],
    ) -> SlotFallbackSuggestion | None:
        self.calls.append(
            {
                "input_text": input_text,
                "normalized_text": normalized_text,
                "template_id": template.template_id,
                "current_slots": dict(current_slots),
                "missing_slots": list(missing_slots),
            }
        )
        return None


def build_one_of_engine(*, slot_resolver: StubTemplateSlotResolver | None = None) -> TemplateCapabilityEngine:
    return TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.25,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.2,
                    "sample": 0.0,
                    "vector": 0.0,
                    "fusion": 0.0,
                    "slot_fit": 0.35,
                    "constraint": 0.15,
                    "structure": 0.3,
                },
                llm_slot_fallback_enabled=slot_resolver is not None,
            ),
            slot_extractors={
                "query_operator": SlotExtractorDefinition(
                    slot_name="query_operator",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {"terms": ["数量", "多少", "几个"], "value": "count"}
                            ],
                        }
                    ],
                ),
                "selector_type": SlotExtractorDefinition(
                    slot_name="selector_type",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {"terms": ["ip"], "value": "ip"},
                                {"terms": ["名称"], "value": "name"},
                            ],
                        }
                    ],
                ),
                "selector_ip": SlotExtractorDefinition(
                    slot_name="selector_ip",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": "ip\\s*(?:为)?\\s*([0-9.]+)",
                                    "group": 1,
                                    "value_type": "string",
                                }
                            ],
                        }
                    ],
                ),
                "selector_name": SlotExtractorDefinition(
                    slot_name="selector_name",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": "名称\\s*(?:为)?\\s*([a-z0-9_.-]+)",
                                    "group": 1,
                                    "value_type": "string",
                                }
                            ],
                        }
                    ],
                ),
                "selector_value": SlotExtractorDefinition(
                    slot_name="selector_value",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": "ip\\s*(?:为)?\\s*([0-9.]+)",
                                    "group": 1,
                                    "value_type": "string",
                                },
                                {
                                    "pattern": "名称\\s*(?:为)?\\s*([a-z0-9_.-]+)",
                                    "group": 1,
                                    "value_type": "string",
                                },
                            ],
                        }
                    ],
                ),
            },
            templates=[
                TemplateDefinition(
                    template_id="device.alarm.by_selector.count",
                    query_mode="metric_query",
                    description="按设备定位方式查询告警数量",
                    utterances=["查询 ip 或 名称 定位的设备告警数量"],
                    required_slots=["query_operator"],
                    optional_slots=[],
                    must_terms=[["设备"], ["告警"], ["数量", "多少", "几个"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["count"]},
                    required_one_of=[
                        SlotGroupRequirement(
                            slots=["selector_ip", "selector_name"],
                            description="至少给一种设备定位方式",
                        )
                    ],
                    mutually_exclusive_slots=[
                        SlotGroupRequirement(
                            slots=["selector_ip", "selector_name"],
                            description="同一次查询里不能同时给 ip 和名称",
                        )
                    ],
                    llm_slot_extraction={
                        "enabled": slot_resolver is not None,
                        "slots": ["selector_ip", "selector_name"],
                    },
                ),
            ],
        ),
        llm_template_slot_resolver=slot_resolver,
    )


def build_conditional_engine() -> TemplateCapabilityEngine:
    return TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.25,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.2,
                    "sample": 0.0,
                    "vector": 0.0,
                    "fusion": 0.0,
                    "slot_fit": 0.35,
                    "constraint": 0.15,
                    "structure": 0.3,
                },
            ),
            slot_extractors={
                "query_operator": SlotExtractorDefinition(
                    slot_name="query_operator",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {"terms": ["数量", "多少", "几个"], "value": "count"}
                            ],
                        }
                    ],
                ),
                "selector_type": SlotExtractorDefinition(
                    slot_name="selector_type",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {"terms": ["ip"], "value": "ip"},
                                {"terms": ["名称"], "value": "name"},
                            ],
                        }
                    ],
                ),
                "selector_value": SlotExtractorDefinition(
                    slot_name="selector_value",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": "ip\\s*(?:为)?\\s*([0-9.]+)",
                                    "group": 1,
                                    "value_type": "string",
                                },
                                {
                                    "pattern": "名称\\s*(?:为)?\\s*([a-z0-9_.-]+)",
                                    "group": 1,
                                    "value_type": "string",
                                },
                            ],
                        }
                    ],
                ),
            },
            templates=[
                TemplateDefinition(
                    template_id="device.alarm.by_selector_type.count",
                    query_mode="metric_query",
                    description="按定位类型和值查询设备告警数量",
                    utterances=["查询 ip 为 10.0.0.1 的设备告警数量"],
                    required_slots=["query_operator", "selector_type"],
                    optional_slots=[],
                    must_terms=[["设备"], ["告警"], ["数量", "多少", "几个"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["count"]},
                    conditional_required=[
                        ConditionalSlotRequirement(
                            when_any=["selector_type"],
                            require=["selector_value"],
                            description="给了定位类型就必须给具体值",
                        )
                    ],
                ),
            ],
        )
    )


def build_generic_vs_selector_engine() -> TemplateCapabilityEngine:
    return TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.2,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.1,
                    "sample": 0.0,
                    "vector": 0.0,
                    "fusion": 0.0,
                    "slot_fit": 0.25,
                    "constraint": 0.15,
                    "structure": 0.5,
                },
            ),
            slot_extractors={
                "query_operator": SlotExtractorDefinition(
                    slot_name="query_operator",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [{"terms": ["数量", "多少", "几个"], "value": "count"}],
                        }
                    ],
                ),
                "selector_ip": SlotExtractorDefinition(
                    slot_name="selector_ip",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [{"pattern": "ip\\s*(?:为)?\\s*([0-9.]+)", "group": 1, "value_type": "string"}],
                        }
                    ],
                ),
                "selector_name": SlotExtractorDefinition(
                    slot_name="selector_name",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [{"pattern": "名称\\s*(?:为)?\\s*([a-z0-9_.-]+)", "group": 1, "value_type": "string"}],
                        }
                    ],
                ),
            },
            templates=[
                TemplateDefinition(
                    template_id="device.alarm.generic.count",
                    query_mode="metric_query",
                    description="查询设备告警数量",
                    utterances=["查询设备告警数量"],
                    required_slots=["query_operator"],
                    optional_slots=[],
                    must_terms=[["设备"], ["告警"], ["数量", "多少", "几个"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["count"]},
                ),
                TemplateDefinition(
                    template_id="device.alarm.by_selector.count",
                    query_mode="metric_query",
                    description="按设备定位方式查询告警数量",
                    utterances=["查询 ip 或 名称 定位的设备告警数量"],
                    required_slots=["query_operator"],
                    optional_slots=[],
                    must_terms=[["设备"], ["告警"], ["数量", "多少", "几个"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["count"]},
                    required_one_of=[
                        SlotGroupRequirement(
                            slots=["selector_ip", "selector_name"],
                            description="至少给一种设备定位方式",
                        )
                    ],
                ),
            ],
        )
    )


def test_required_one_of_keeps_old_contract_and_returns_partial_when_none_present():
    payload = build_one_of_engine().match("查询设备告警数量").to_dict()

    assert payload["template_id"] == "device.alarm.by_selector.count"
    assert payload["status"] == MatchStatus.PARTIAL.value
    assert payload["missing_slots"] == ["selector_ip", "selector_name"]
    assert payload["trace"]["requirement_issues"][0]["kind"] == "required_one_of"


def test_required_one_of_matches_when_any_selector_is_present():
    payload = build_one_of_engine().match("查询名称为core-sw的设备告警数量").to_dict()

    assert payload["template_id"] == "device.alarm.by_selector.count"
    assert payload["status"] == MatchStatus.MATCHED.value
    assert payload["slots"]["selector_name"] == "core-sw"


def test_conditional_required_enforces_if_a_then_b():
    partial_payload = build_conditional_engine().match("查询ip的设备告警数量").to_dict()
    matched_payload = build_conditional_engine().match("查询ip为10.0.0.1的设备告警数量").to_dict()

    assert partial_payload["template_id"] == "device.alarm.by_selector_type.count"
    assert partial_payload["status"] == MatchStatus.PARTIAL.value
    assert partial_payload["missing_slots"] == ["selector_value"]
    assert partial_payload["trace"]["requirement_issues"][0]["kind"] == "conditional_required"
    assert partial_payload["trace"]["requirement_issues"][0]["trigger_slots"] == ["selector_type"]

    assert matched_payload["template_id"] == "device.alarm.by_selector_type.count"
    assert matched_payload["status"] == MatchStatus.MATCHED.value
    assert matched_payload["slots"]["selector_value"] == "10.0.0.1"


def test_mutually_exclusive_slots_produce_conflict_style_partial():
    payload = build_one_of_engine().match("查询ip为10.0.0.1 名称为core-sw的设备告警数量").to_dict()

    assert payload["template_id"] == "device.alarm.by_selector.count"
    assert payload["status"] == MatchStatus.PARTIAL.value
    assert payload["missing_slots"] == []
    assert payload["trace"]["requirement_issues"][0]["kind"] == "mutually_exclusive_slots"
    assert payload["trace"]["requirement_issues"][0]["slots"] == ["selector_ip", "selector_name"]


def test_conflict_only_partial_does_not_trigger_template_slot_fallback():
    slot_resolver = StubTemplateSlotResolver()
    payload = build_one_of_engine(slot_resolver=slot_resolver).match(
        "查询ip为10.0.0.1 名称为core-sw的设备告警数量"
    ).to_dict()

    assert payload["status"] == MatchStatus.PARTIAL.value
    assert payload["missing_slots"] == []
    assert slot_resolver.calls == []


def test_partial_selector_template_is_penalized_below_generic_match():
    payload = build_generic_vs_selector_engine().match("查询设备告警数量").to_dict()
    top_candidates = payload["trace"]["top_candidates"]
    selector_candidate = next(
        candidate
        for candidate in top_candidates
        if candidate["template_id"] == "device.alarm.by_selector.count"
    )

    assert payload["template_id"] == "device.alarm.generic.count"
    assert payload["status"] == MatchStatus.MATCHED.value
    assert selector_candidate["missing_slots"] == ["selector_ip", "selector_name"]
    assert selector_candidate["trace"]["requirement_issues"][0]["kind"] == "required_one_of"
    assert selector_candidate["trace"]["structure_details"]["key_requirement_penalty"] < 1.0
    assert payload["trace"]["selected_template"]["structure_score"] > selector_candidate["structure_score"]
