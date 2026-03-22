from __future__ import annotations

from template_capability.config import TemplateConfig
from template_capability.engine import TemplateCapabilityEngine
from template_capability.models import MatcherSettings, SlotExtractorDefinition, TemplateDefinition
from template_capability.vector_index import LocalHashVectorProvider, LocalTfidfVectorProvider, RemoteEmbeddingProvider


def test_engine_uses_configured_hash_vector_provider():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.58,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={"lexical": 1.0},
                vector_provider="hashing",
                vector_dimension=64,
            ),
            templates=[],
        )
    )

    assert isinstance(engine.vector_backend.provider, LocalHashVectorProvider)
    assert engine.vector_backend.provider.dimension == 64


def test_engine_uses_remote_vector_provider_with_env_api_key(monkeypatch):
    monkeypatch.setenv("REMOTE_EMBEDDING_API_KEY", "env-secret")
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.58,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={"lexical": 1.0},
                vector_provider="remote",
                vector_dimension=128,
                vector_options={
                    "base_url": "https://example.invalid/v1",
                    "model": "demo-embedding",
                    "api_key_env": "REMOTE_EMBEDDING_API_KEY",
                    "include_dimensions": False,
                },
            ),
            templates=[],
        )
    )

    provider = engine.vector_backend.provider
    assert isinstance(provider, RemoteEmbeddingProvider)
    assert provider.api_key == "env-secret"
    assert provider.base_url == "https://example.invalid/v1"
    assert provider.model == "demo-embedding"
    assert provider.dimension == 128
    assert provider.include_dimensions is False


def test_global_slots_appear_in_trace_and_penalize_underfit_template():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.3,
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
                vector_provider="local_tfidf",
                vector_dimension=64,
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
                            "cases": [{"terms": ["列表"], "value": "list"}],
                        }
                    ],
                ),
                "cpu_threshold": SlotExtractorDefinition(
                    slot_name="cpu_threshold",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": "cpu\\s*(?:大于|超过|高于)\\s*(\\d+)",
                                    "group": 1,
                                    "value_type": "int",
                                }
                            ],
                        }
                    ],
                ),
                "memory_threshold": SlotExtractorDefinition(
                    slot_name="memory_threshold",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": "内存\\s*(?:大于|超过|高于)\\s*(\\d+)",
                                    "group": 1,
                                    "value_type": "int",
                                }
                            ],
                        }
                    ],
                ),
            },
            templates=[
                TemplateDefinition(
                    template_id="device.cpu.only.list",
                    query_mode="metric_query",
                    description="查询 cpu 超阈值设备列表",
                    utterances=["近24小时 cpu 大于 80 的设备列表"],
                    required_slots=["query_operator", "cpu_threshold"],
                    optional_slots=["time_range"],
                    must_terms=[["cpu"], ["设备"], ["列表"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["list"]},
                ),
                TemplateDefinition(
                    template_id="device.cpu.memory.list",
                    query_mode="metric_query",
                    description="查询 cpu 和内存同时超阈值的设备列表",
                    utterances=["近24小时 cpu 大于 80 且 内存 大于 70 的设备列表"],
                    required_slots=["query_operator", "cpu_threshold", "memory_threshold"],
                    optional_slots=["time_range"],
                    must_terms=[["cpu"], ["内存"], ["设备"], ["列表"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["list"]},
                ),
            ],
        )
    )

    payload = engine.match("近24小时 cpu 大于 80 且 内存 大于 70 的设备列表").to_dict()

    assert payload["template_id"] == "device.cpu.memory.list"
    assert payload["trace"]["global_slots"]["cpu_threshold"] == 80
    assert payload["trace"]["global_slots"]["memory_threshold"] == 70

    cpu_only_candidate = next(
        candidate
        for candidate in payload["trace"]["top_candidates"]
        if candidate["template_id"] == "device.cpu.only.list"
    )
    assert cpu_only_candidate["trace"]["unexpected_global_slots"] == ["memory_threshold"]
    assert cpu_only_candidate["trace"]["structure_details"]["support_coverage_score"] < 1.0
    assert cpu_only_candidate["trace"]["structure_details"]["unsupported_query_slots"] == ["memory_threshold"]
    assert payload["trace"]["selected_template"]["score"] > cpu_only_candidate["score"]


def test_structure_score_descends_with_query_complexity():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.2,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.05,
                    "sample": 0.0,
                    "vector": 0.0,
                    "fusion": 0.0,
                    "slot_fit": 0.2,
                    "constraint": 0.1,
                    "structure": 0.65,
                },
                vector_provider="local_tfidf",
                vector_dimension=64,
            ),
            slot_extractors={
                "query_operator": SlotExtractorDefinition(
                    slot_name="query_operator",
                    extractors=[
                        {
                            "type": "keyword_value",
                            "cases": [{"terms": ["列表"], "value": "list"}],
                        }
                    ],
                ),
                "cpu_threshold": SlotExtractorDefinition(
                    slot_name="cpu_threshold",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [{"pattern": "cpu\\s*大于\\s*(\\d+)", "group": 1, "value_type": "int"}],
                        }
                    ],
                ),
                "memory_threshold": SlotExtractorDefinition(
                    slot_name="memory_threshold",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [{"pattern": "内存\\s*大于\\s*(\\d+)", "group": 1, "value_type": "int"}],
                        }
                    ],
                ),
                "disk_threshold": SlotExtractorDefinition(
                    slot_name="disk_threshold",
                    extractors=[
                        {
                            "type": "regex",
                            "patterns": [{"pattern": "磁盘\\s*大于\\s*(\\d+)", "group": 1, "value_type": "int"}],
                        }
                    ],
                ),
            },
            templates=[
                TemplateDefinition(
                    template_id="device.cpu.list",
                    query_mode="metric_query",
                    description="查询 cpu 超阈值设备列表",
                    utterances=["cpu 大于 80 的设备列表"],
                    required_slots=["query_operator", "cpu_threshold"],
                    optional_slots=[],
                    must_terms=[["cpu"], ["设备"], ["列表"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["list"]},
                ),
                TemplateDefinition(
                    template_id="device.cpu.memory.list",
                    query_mode="metric_query",
                    description="查询 cpu 和内存超阈值设备列表",
                    utterances=["cpu 大于 80 且 内存 大于 70 的设备列表"],
                    required_slots=["query_operator", "cpu_threshold", "memory_threshold"],
                    optional_slots=[],
                    must_terms=[["cpu"], ["内存"], ["设备"], ["列表"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["list"]},
                ),
                TemplateDefinition(
                    template_id="device.cpu.memory.disk.list",
                    query_mode="metric_query",
                    description="查询 cpu 内存 磁盘都超阈值的设备列表",
                    utterances=["cpu 大于 80 且 内存 大于 70 且 磁盘 大于 85 的设备列表"],
                    required_slots=["query_operator", "cpu_threshold", "memory_threshold", "disk_threshold"],
                    optional_slots=[],
                    must_terms=[["cpu"], ["内存"], ["磁盘"], ["设备"], ["列表"]],
                    negative_terms=[],
                    slot_constraints={"query_operator": ["list"]},
                ),
            ],
        )
    )

    payload = engine.match("cpu 大于 80 且 内存 大于 70 且 磁盘 大于 85 的设备列表").to_dict()
    candidates = payload["trace"]["top_candidates"]

    assert payload["template_id"] == "device.cpu.memory.disk.list"
    assert [candidate["template_id"] for candidate in candidates[:3]] == [
        "device.cpu.memory.disk.list",
        "device.cpu.memory.list",
        "device.cpu.list",
    ]
    assert candidates[0]["structure_score"] > candidates[1]["structure_score"] > candidates[2]["structure_score"]
    assert candidates[1]["trace"]["structure_details"]["unsupported_query_slots"] == ["disk_threshold"]
    assert candidates[2]["trace"]["structure_details"]["unsupported_query_slots"] == ["disk_threshold", "memory_threshold"]


def test_engine_uses_local_tfidf_by_default():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.58,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={"lexical": 1.0},
            ),
            templates=[],
        )
    )

    assert isinstance(engine.vector_backend.provider, LocalTfidfVectorProvider)
