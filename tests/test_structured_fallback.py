from __future__ import annotations

from types import SimpleNamespace

from template_capability.fallback import OpenAICompatibleFallbackResolver, OpenAICompatibleTemplateSlotResolver
from template_capability.models import MatchStatus, TemplateCandidate, TemplateDefinition


def test_template_slot_resolver_falls_back_to_json_object_when_json_schema_is_not_supported():
    seen_response_formats: list[str] = []

    class FakeCompletions:
        def create(self, **payload):
            response_format = payload["response_format"]["type"]
            seen_response_formats.append(response_format)
            if response_format == "json_schema":
                raise RuntimeError("json_schema not supported")
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"slots": {"topn": 10, "ignored_slot": 99}, "reason": "filled from query"}'
                        }
                    }
                ]
            }

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    resolver = OpenAICompatibleTemplateSlotResolver(
        api_key="demo-key",
        base_url="https://example.invalid/v1",
        model="demo-model",
        client=fake_client,
    )
    template = TemplateDefinition(
        template_id="alarm.rank.demo",
        query_mode="metric_query",
        description="查询接口错误包告警排行",
        utterances=["近24小时接口错误包告警前十"],
        required_slots=["topn"],
        optional_slots=[],
        must_terms=[["告警"], ["前", "top"]],
        negative_terms=[],
        slot_constraints={},
        slot_extractors={},
        llm_slot_extraction={"enabled": True, "slots": ["topn"]},
    )

    suggestion = resolver.resolve_slots(
        input_text="近24小时接口错误包告警前十",
        normalized_text="近24小时接口错误包告警前十",
        template=template,
        current_slots={},
        missing_slots=["topn"],
    )

    assert suggestion is not None
    assert suggestion.slots == {"topn": 10}
    assert suggestion.trace["response_format_mode"] == "json_object"
    assert seen_response_formats == ["json_schema", "json_object"]


def test_template_selection_resolver_uses_json_schema_and_only_fills_missing_slots():
    captured_response_format: list[str] = []

    class FakeCompletions:
        def create(self, **payload):
            captured_response_format.append(payload["response_format"]["type"])
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"template_id": "alarm.rank.demo", "status": "matched", '
                                '"slots": {"topn": 10, "query_operator": "count"}, '
                                '"score": 0.93, "reason": "best candidate"}'
                            )
                        }
                    }
                ]
            }

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    resolver = OpenAICompatibleFallbackResolver(
        api_key="demo-key",
        base_url="https://example.invalid/v1",
        model="demo-model",
        client=fake_client,
    )
    template = TemplateDefinition(
        template_id="alarm.rank.demo",
        query_mode="metric_query",
        description="查询接口错误包告警排行",
        utterances=["近24小时接口错误包告警前十"],
        required_slots=["query_operator", "topn"],
        optional_slots=[],
        must_terms=[["告警"], ["前", "top"]],
        negative_terms=[],
        slot_constraints={"query_operator": ["topn"]},
    )
    candidate = TemplateCandidate(
        template_id="alarm.rank.demo",
        query_mode="metric_query",
        score=0.61,
        lexical_score=0.61,
        sample_score=0.0,
        vector_score=0.0,
        fusion_score=0.0,
        rerank_score=0.0,
        slot_fit_score=0.0,
        constraint_score=0.0,
        structure_score=0.0,
        slots={"query_operator": "topn"},
        missing_slots=["topn"],
        trace={"source": "candidate"},
    )

    suggestion = resolver.resolve(
        input_text="近24小时接口错误包告警排行",
        normalized_text="近24小时接口错误包告警排行",
        slots={"query_operator": "topn"},
        candidates=[candidate],
        templates={"alarm.rank.demo": template},
    )

    assert suggestion is not None
    assert suggestion.template_id == "alarm.rank.demo"
    assert suggestion.status is MatchStatus.MATCHED
    assert suggestion.slots == {"query_operator": "topn", "topn": 10}
    assert suggestion.score == 0.93
    assert suggestion.trace["response_format_mode"] == "json_schema"
    assert captured_response_format == ["json_schema"]


def test_template_selection_resolver_can_return_unmatched():
    class FakeCompletions:
        def create(self, **payload):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"template_id": "-1", "status": "unmatched", "reason": "none reliable"}'
                        }
                    }
                ]
            }

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    resolver = OpenAICompatibleFallbackResolver(
        api_key="demo-key",
        base_url="https://example.invalid/v1",
        model="demo-model",
        client=fake_client,
    )
    template = TemplateDefinition(
        template_id="tmpl.a",
        query_mode="metric_query",
        description="查询离线设备数",
        utterances=["昨天离线设备数"],
        required_slots=[],
        optional_slots=[],
        must_terms=[["离线"], ["设备"]],
        negative_terms=[],
        slot_constraints={},
    )
    candidate = TemplateCandidate(
        template_id="tmpl.a",
        query_mode="metric_query",
        score=0.59,
        lexical_score=0.59,
        sample_score=0.0,
        vector_score=0.0,
        fusion_score=0.0,
        rerank_score=0.0,
        slot_fit_score=0.0,
        constraint_score=0.0,
        structure_score=0.0,
        slots={},
        missing_slots=[],
    )

    suggestion = resolver.resolve(
        input_text="帮我分析离线原因",
        normalized_text="帮我分析离线原因",
        slots={},
        candidates=[candidate],
        templates={"tmpl.a": template},
    )

    assert suggestion is not None
    assert suggestion.template_id == -1
    assert suggestion.status is MatchStatus.UNMATCHED
