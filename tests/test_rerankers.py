from __future__ import annotations

from types import SimpleNamespace

from template_capability.config import TemplateConfig
from template_capability.engine import TemplateCapabilityEngine
from template_capability.models import MatcherSettings, TemplateCandidate, TemplateDefinition
from template_capability.rerankers import (
    OpenAICompatibleTemplateReranker,
    RerankScore,
    TermOverlapTemplateReranker,
)


class StubTemplateReranker:
    def rerank(
        self,
        *,
        normalized_text: str,
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
        template_documents: dict[str, str],
    ) -> dict[str, RerankScore]:
        return {
            "template.target": RerankScore(score=1.0, trace={"provider": "stub", "query": normalized_text}),
            "template.baseline": RerankScore(score=0.0, trace={"provider": "stub", "query": normalized_text}),
        }


def test_engine_uses_configured_term_overlap_reranker():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.3,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={"lexical": 1.0},
                reranker_enabled=True,
                reranker_provider="term_overlap",
            ),
            templates=[],
        )
    )

    assert isinstance(engine.template_reranker, TermOverlapTemplateReranker)
    assert "rerank" in engine.config.settings.weights


def test_injected_reranker_reorders_top_candidates_and_exposes_trace():
    engine = TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.1,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.2,
                    "sample": 0.0,
                    "vector": 0.0,
                    "fusion": 0.0,
                    "slot_fit": 0.0,
                    "constraint": 0.0,
                    "structure": 0.0,
                    "rerank": 0.8,
                },
                reranker_enabled=True,
                reranker_provider="term_overlap",
                reranker_top_k=5,
            ),
            templates=[
                TemplateDefinition(
                    template_id="template.baseline",
                    query_mode="metric_query",
                    description="查询最近 cpu 大于 80 的设备列表",
                    utterances=["查询最近 cpu 大于 80 的设备列表"],
                    required_slots=[],
                    optional_slots=[],
                    must_terms=[["cpu"], ["列表"]],
                    negative_terms=[],
                    slot_constraints={},
                ),
                TemplateDefinition(
                    template_id="template.target",
                    query_mode="metric_query",
                    description="查询近24小时 cpu 大于 80 的设备列表",
                    utterances=["查询近24小时 cpu 大于 80 的设备列表"],
                    required_slots=[],
                    optional_slots=[],
                    must_terms=[["cpu"], ["列表"]],
                    negative_terms=[],
                    slot_constraints={},
                ),
            ],
        ),
        template_reranker=StubTemplateReranker(),
    )

    payload = engine.match("查询最近 cpu 大于 80 的设备列表").to_dict()
    top_candidates = payload["trace"]["top_candidates"]

    assert payload["template_id"] == "template.target"
    assert top_candidates[0]["template_id"] == "template.target"
    assert top_candidates[0]["rerank_score"] == 1.0
    assert top_candidates[0]["trace"]["rerank_trace"]["provider"] == "stub"
    assert top_candidates[1]["template_id"] == "template.baseline"
    assert top_candidates[1]["rerank_score"] == 0.0


def test_openai_compatible_reranker_parses_scores_from_stub_client():
    recorded_payload: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **payload):
            recorded_payload.update(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"scores": {"template.cpu": 0.91, "unknown.template": 0.2}}'
                        }
                    }
                ]
            }

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    reranker = OpenAICompatibleTemplateReranker(
        api_key="demo-key",
        base_url="https://example.invalid/v1",
        model="demo-model",
        client=fake_client,
    )
    template = TemplateDefinition(
        template_id="template.cpu",
        query_mode="metric_query",
        description="查询 cpu 利用率",
        utterances=["查询 cpu 利用率"],
        required_slots=[],
        optional_slots=[],
        must_terms=[["cpu"]],
        negative_terms=[],
        slot_constraints={},
    )
    candidate = TemplateCandidate(
        template_id="template.cpu",
        query_mode="metric_query",
        score=0.6,
        lexical_score=0.6,
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

    scores = reranker.rerank(
        normalized_text="查询 cpu 利用率",
        candidates=[candidate],
        templates={"template.cpu": template},
        template_documents={"template.cpu": "查询 cpu 利用率"},
    )

    assert recorded_payload["response_format"] == {"type": "json_object"}
    assert scores["template.cpu"].score == 0.91
    assert scores["template.cpu"].trace["provider"] == "openai_compatible"
    assert scores["template.cpu"].trace["model"] == "demo-model"
