from __future__ import annotations

import time

from template_capability.config import TemplateConfig
from template_capability.engine import TemplateCapabilityEngine
from template_capability.fallback import FallbackSuggestion
from template_capability.models import MatchStatus, MatcherSettings, SlotExtractorDefinition, TemplateDefinition


class StubVectorBackend:
    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.queries: list[tuple[str, int]] = []

    def build(self, documents: dict[str, str]) -> None:
        self.documents = dict(documents)

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        self.queries.append((query_text, top_k))
        return []


class StubFallbackResolver:
    def __init__(self, suggestion: FallbackSuggestion | None) -> None:
        self.suggestion = suggestion
        self.calls: list[dict[str, object]] = []

    def resolve(
        self,
        *,
        input_text: str,
        normalized_text: str,
        slots: dict[str, object],
        candidates: list[object],
        templates: dict[str, object],
    ) -> FallbackSuggestion | None:
        self.calls.append(
            {
                "input_text": input_text,
                "normalized_text": normalized_text,
                "slots": dict(slots),
                "candidate_count": len(candidates),
                "template_count": len(templates),
            }
        )
        return self.suggestion


def test_custom_vector_backend_can_be_injected():
    backend = StubVectorBackend()
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.58,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.7,
                    "vector": 0.0,
                    "slot_fit": 0.2,
                    "constraint": 0.1,
                },
                vector_dimension=512,
            ),
            slot_extractors={
                "time_range": SlotExtractorDefinition(
                    slot_name="time_range",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {
                                    "terms": ["近24小时"],
                                    "value": {"mode": "relative", "preset": "last_24h"},
                                }
                            ],
                        }
                    ],
                ),
                "topn": SlotExtractorDefinition(
                    slot_name="topn",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": "(?:top\\s*|前)\\s*(\\d+)",
                                    "group": 1,
                                    "value_type": "int",
                                    "min": 1,
                                    "max": 1000,
                                }
                            ],
                        }
                    ],
                ),
                "query_operator": SlotExtractorDefinition(
                    slot_name="query_operator",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {"terms": ["top", "前", "排名", "排行"], "value": "topn"}
                            ],
                        }
                    ],
                ),
            },
            templates=[
                TemplateDefinition(
                    template_id="metric.rank.demo",
                    query_mode="metric_query",
                    description="查询演示指标排名",
                    utterances=["近24小时演示指标Top10"],
                    required_slots=["time_range", "topn"],
                    optional_slots=[],
                    must_terms=[["演示指标"], ["top", "前", "排名", "排行"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["topn"]},
                )
            ],
        ),
        vector_backend=backend,
    )

    payload = engine.match("近24小时演示指标Top10").to_dict()
    assert payload["template_id"] == "metric.rank.demo"
    assert backend.documents
    assert backend.queries == [("近24小时演示指标top10", 10)]


def test_llm_fallback_can_upgrade_partial_result():
    backend = StubVectorBackend()
    fallback = StubFallbackResolver(
        FallbackSuggestion(
            template_id="metric.rank.demo",
            status=MatchStatus.MATCHED,
            score=0.91,
            query_mode="metric_query",
            slots={
                "time_range": {"mode": "relative", "preset": "last_24h"},
                "topn": 10,
                "query_operator": "topn",
            },
            trace={"source": "stub"},
        )
    )
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.58,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.7,
                    "vector": 0.0,
                    "slot_fit": 0.2,
                    "constraint": 0.1,
                },
                vector_dimension=512,
                llm_fallback_enabled=True,
                llm_fallback_max_candidates=2,
                llm_fallback_max_missing_slots=2,
            ),
            slot_extractors={
                "time_range": SlotExtractorDefinition(
                    slot_name="time_range",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {
                                    "terms": ["近24小时"],
                                    "value": {"mode": "relative", "preset": "last_24h"},
                                }
                            ],
                        }
                    ],
                ),
                "query_operator": SlotExtractorDefinition(
                    slot_name="query_operator",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [
                                {"terms": ["top", "前", "排名", "排行"], "value": "topn"}
                            ],
                        }
                    ],
                ),
            },
            templates=[
                TemplateDefinition(
                    template_id="metric.rank.demo",
                    query_mode="metric_query",
                    description="查询演示指标排名",
                    utterances=["近24小时演示指标Top10"],
                    required_slots=["time_range", "query_operator", "topn"],
                    optional_slots=[],
                    must_terms=[["演示指标"], ["top", "前", "排名", "排行"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["topn"]},
                )
            ],
        ),
        vector_backend=backend,
        llm_fallback_resolver=fallback,
    )

    payload = engine.match("近24小时演示指标排行").to_dict()
    assert payload["template_id"] == "metric.rank.demo"
    assert payload["status"] == "matched"
    assert payload["trace"]["fallback_used"] is True
    assert fallback.calls


def test_llm_fallback_stays_off_for_blocked_queries():
    fallback = StubFallbackResolver(
        FallbackSuggestion(
            template_id="metric.rank.demo",
            status=MatchStatus.MATCHED,
            score=0.91,
            query_mode="metric_query",
        )
    )
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.58,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.7,
                    "vector": 0.0,
                    "slot_fit": 0.2,
                    "constraint": 0.1,
                },
                vector_dimension=512,
                blocked_terms=["分析"],
                llm_fallback_enabled=True,
            ),
            slot_extractors={},
            templates=[
                TemplateDefinition(
                    template_id="metric.rank.demo",
                    query_mode="metric_query",
                    description="查询演示指标排名",
                    utterances=["近24小时演示指标Top10"],
                    required_slots=[],
                    optional_slots=[],
                    must_terms=[["演示指标"]],
                    negative_terms=[],
                    slot_constraints={},
                )
            ],
        ),
        llm_fallback_resolver=fallback,
    )

    payload = engine.match("分析演示指标").to_dict()
    assert payload["template_id"] == -1
    assert payload["status"] == "unmatched"
    assert fallback.calls == []


def test_ambiguous_templates_return_minus_one():
    config = TemplateConfig(
        settings=MatcherSettings(
            match_threshold=0.58,
            ambiguity_margin=0.03,
            recall_top_k=10,
            weights={
                "lexical": 0.7,
                "vector": 0.0,
                "slot_fit": 0.2,
                "constraint": 0.1,
            },
            vector_dimension=512,
        ),
        slot_extractors={
            "time_range": SlotExtractorDefinition(
                slot_name="time_range",
                extractors=[
                    {
                        "type": "keyword_value",
                        "cases": [
                            {
                                "terms": ["昨天"],
                                "value": {"mode": "relative", "preset": "yesterday"},
                            }
                        ],
                    }
                ],
            ),
            "query_operator": SlotExtractorDefinition(
                slot_name="query_operator",
                extractors=[
                    {
                        "type": "keyword_value",
                        "cases": [
                            {"terms": ["数量", "数", "有多少"], "value": "count"}
                        ],
                    }
                ],
            ),
        },
        templates=[
            TemplateDefinition(
                template_id="tmpl.a",
                query_mode="metric_query",
                description="查询昨天华东离线设备数量",
                utterances=["昨天华东离线设备数量"],
                required_slots=["time_range", "query_operator"],
                optional_slots=[],
                must_terms=[["离线"], ["设备"], ["数量", "数", "有多少"]],
                negative_terms=[],
                slot_constraints={"query_operator": ["count"]},
            ),
            TemplateDefinition(
                template_id="tmpl.b",
                query_mode="metric_query",
                description="查询昨天华东掉线设备数量",
                utterances=["昨天华东掉线设备数量"],
                required_slots=["time_range", "query_operator"],
                optional_slots=[],
                must_terms=[["掉线"], ["设备"], ["数量", "数", "有多少"]],
                negative_terms=[],
                slot_constraints={"query_operator": ["count"]},
            ),
        ],
    )

    payload = TemplateCapabilityEngine(config).match("昨天华东设备数量").to_dict()
    assert payload["template_id"] == -1
    assert payload["status"] == "unmatched"


def test_engine_handles_thousand_templates_quickly():
    slot_extractors = {
        "time_range": SlotExtractorDefinition(
            slot_name="time_range",
            extractors=[
                {
                    "type": "keyword_value",
                    "cases": [
                        {
                            "terms": ["近24小时"],
                            "value": {"mode": "relative", "preset": "last_24h"},
                        }
                    ],
                }
            ],
        ),
        "topn": SlotExtractorDefinition(
            slot_name="topn",
            extractors=[
                {
                    "type": "regex",
                    "patterns": [
                        {
                            "pattern": "(?:top\\s*|前)\\s*(\\d+)",
                            "group": 1,
                            "value_type": "int",
                            "min": 1,
                            "max": 1000,
                        }
                    ],
                }
            ],
        ),
        "query_operator": SlotExtractorDefinition(
            slot_name="query_operator",
            extractors=[
                {
                    "type": "keyword_value",
                    "cases": [
                        {"terms": ["top", "前", "排名", "排行"], "value": "topn"}
                    ],
                }
            ],
        ),
    }
    templates = [
        TemplateDefinition(
            template_id=f"metric.rank.{idx}",
            query_mode="metric_query",
            description=f"查询指标{idx}排行",
            utterances=[f"近24小时指标{idx}Top10", f"查询指标{idx}排名前10"],
            required_slots=["time_range", "topn"],
            optional_slots=[],
            must_terms=[[f"指标{idx}"], ["top", "前", "排名", "排行"]],
            negative_terms=[],
            slot_constraints={"query_operator": ["topn"]},
        )
        for idx in range(1000)
    ]
    config = TemplateConfig(
        settings=MatcherSettings(
            match_threshold=0.58,
            ambiguity_margin=0.03,
            recall_top_k=40,
            weights={
                "lexical": 0.55,
                "vector": 0.15,
                "slot_fit": 0.2,
                "constraint": 0.1,
            },
            vector_dimension=512,
        ),
        slot_extractors=slot_extractors,
        templates=templates,
    )

    start = time.perf_counter()
    engine = TemplateCapabilityEngine(config)
    build_elapsed = time.perf_counter() - start

    start = time.perf_counter()
    payload = engine.match("近24小时指标777 Top10").to_dict()
    match_elapsed = time.perf_counter() - start

    assert payload["template_id"] == "metric.rank.777"
    assert payload["status"] == "matched"
    assert build_elapsed < 3.0
    assert match_elapsed < 1.0
