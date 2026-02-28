from __future__ import annotations

import time

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.application.services.scoring import (
    example_similarity_score,
    keyword_overlap_score,
    slot_fit_score,
    weighted_score,
)
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.interfaces import Retriever, TemplateRepository
from chat_pre_check.domain.models import RequestContext, RouteDecision, SearchHit, TraceStep


class TemplateMatcherMiddleware:
    name = "template_matcher"

    def __init__(
        self,
        template_repository: TemplateRepository,
        retriever: Retriever,
        recommendation_service: RecommendationService,
        threshold: float,
        fusion_weights: dict[str, float],
        template_topk: int,
    ) -> None:
        self.template_repository = template_repository
        self.retriever = retriever
        self.recommendation_service = recommendation_service
        self.threshold = threshold
        self.fusion_weights = fusion_weights
        self.template_topk = template_topk

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if not ctx.scene:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="scene_absent_skip",
                    latency_ms=elapsed,
                )
            )
            return None

        templates = self.template_repository.by_scene(ctx.scene)
        if not templates:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="template_empty",
                    latency_ms=elapsed,
                )
            )
            return None

        try:
            vector_hits = self.retriever.search_template(
                scene_id=ctx.scene,
                query_text=ctx.norm_text,
                topk=self.template_topk,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="template_retrieval_failed",
                    latency_ms=elapsed,
                    extra={"error": str(exc)},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="模板召回依赖暂时不可用，请稍后重试。",
                scene=ctx.scene,
                slots=dict(ctx.slots),
                options=self.recommendation_service.refuse_options(
                    ctx, OutOfScopeReason.DATA_UNAVAILABLE
                ),
                out_of_scope_reason=OutOfScopeReason.DATA_UNAVAILABLE,
            )
        vector_map = self._vector_map(vector_hits, key="template_id")

        scored: list[tuple[str, float, dict[str, float], dict]] = []
        for template in templates:
            template_id = template["template_id"]
            score_parts = {
                "rule": max(
                    keyword_overlap_score(ctx.norm_text, template.get("keywords", [])),
                    example_similarity_score(ctx.norm_text, template.get("examples", [])),
                ),
                "vector": vector_map.get(template_id, 0.0),
                "slot_fit": slot_fit_score(template.get("slot_schema", {}), ctx.slots),
            }
            if self._contains_negative_keyword(
                ctx.norm_text, template.get("negative_keywords", [])
            ):
                score_parts["rule"] = 0.0
            total = weighted_score(score_parts, self.fusion_weights)
            scored.append((template_id, total, score_parts, template))

        scored.sort(key=lambda item: item[1], reverse=True)
        top_template_id, top_score, top_parts, top_template = scored[0]
        ctx.trace.summary["template_top1"] = top_template_id

        if top_score < self.threshold:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="below_template_threshold",
                    latency_ms=elapsed,
                    score=top_score,
                    topk=[
                        {"template_id": tid, "score": score}
                        for tid, score, _parts, _tpl in scored[:5]
                    ],
                    extra={"threshold": self.threshold},
                )
            )
            return None

        required = top_template.get("slot_schema", {}).get("required", [])
        missing_slots = [slot for slot in required if ctx.slots.get(slot) in (None, "")]
        if missing_slots:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="clarify",
                    reason="template_hit_but_slots_missing",
                    latency_ms=elapsed,
                    score=top_score,
                    topk=[{"template_id": top_template_id, "score": top_score}],
                    extra={"missing_slots": missing_slots},
                )
            )
            return RouteDecision(
                type=DecisionType.CLARIFY,
                message="模板已命中，但仍缺少必要参数。",
                scene=ctx.scene,
                slots=dict(ctx.slots),
                missing_slots=missing_slots[:2],
                options=self.recommendation_service.slot_clarify_options(
                    missing_slots[0], ctx
                ),
            )

        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="route_template",
                reason="template_hit",
                latency_ms=elapsed,
                score=top_score,
                topk=[{"template_id": top_template_id, "score": top_score}],
                extra={"score_parts": top_parts},
            )
        )
        return RouteDecision(
            type=DecisionType.ROUTE_TEMPLATE,
            message="已命中可执行模板。",
            scene=ctx.scene,
            template_id=top_template_id,
            slots=dict(ctx.slots),
            missing_slots=[],
            options=[],
        )

    @staticmethod
    def _vector_map(hits: list[SearchHit], key: str) -> dict[str, float]:
        mapping: dict[str, float] = {}
        if not hits:
            return mapping
        max_score = max(hit.score for hit in hits) or 1.0
        for hit in hits:
            candidate_key = hit.metadata.get(key)
            if candidate_key is None:
                continue
            mapping[candidate_key] = max(mapping.get(candidate_key, 0.0), hit.score / max_score)
        return mapping

    @staticmethod
    def _contains_negative_keyword(text: str, keywords: list[str]) -> bool:
        text = text.lower()
        return any(keyword.lower() in text for keyword in keywords)
