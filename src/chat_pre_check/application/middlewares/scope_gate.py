from __future__ import annotations

import time
from typing import Any

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.application.services.scoring import (
    entity_coverage_score,
    example_similarity_score,
    keyword_overlap_score,
    weighted_score,
)
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.interfaces import Retriever, SceneRepository
from chat_pre_check.domain.models import RequestContext, RouteDecision, SearchHit, TraceStep


class ScopeGateMiddleware:
    """场景闸门：融合规则分与向量分，判断是否在支持范围内。"""

    name = "scope_gate"

    def __init__(
        self,
        scene_repository: SceneRepository,
        retriever: Retriever,
        recommendation_service: RecommendationService,
        thresholds: dict[str, float],
        fusion_weights: dict[str, float],
        scene_topk: int,
    ) -> None:
        self.scene_repository = scene_repository
        self.retriever = retriever
        self.recommendation_service = recommendation_service
        self.thresholds = thresholds
        self.fusion_weights = fusion_weights
        self.scene_topk = scene_topk

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if ctx.scene and self.scene_repository.get(ctx.scene):
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="scene_preselected",
                    latency_ms=elapsed,
                    extra={"scene": ctx.scene},
                )
            )
            return None

        if ctx.context_scene and self.scene_repository.get(ctx.context_scene):
            # 上下文显式指定且存在的场景优先。
            ctx.scene = ctx.context_scene
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="context_scene_override",
                    latency_ms=elapsed,
                    extra={"scene": ctx.context_scene},
                )
            )
            return None

        scenes = self.scene_repository.all_enabled()
        if ctx.flow_type:
            scenes = [
                item
                for item in scenes
                if str(item.get("flow_type", "query")).strip().lower() == ctx.flow_type
            ]
            if not scenes:
                elapsed = (time.perf_counter() - started) * 1000
                ctx.trace.add_step(
                    TraceStep(
                        step=self.name,
                        decision="refuse",
                        reason="flow_without_scene",
                        latency_ms=elapsed,
                        extra={"flow_type": ctx.flow_type},
                    )
                )
                return RouteDecision(
                    type=DecisionType.REFUSE,
                    message="当前业务流暂未接入可执行场景。",
                    flow_type=ctx.flow_type,
                    slots=dict(ctx.slots),
                    options=self.recommendation_service.refuse_options(
                        ctx, OutOfScopeReason.UNSUPPORTED_DOMAIN
                    ),
                    out_of_scope_reason=OutOfScopeReason.UNSUPPORTED_DOMAIN,
                    clarify_round=ctx.clarify_round,
                    max_clarify_round=ctx.max_clarify_round,
                    next_action="refuse",
                )
        try:
            vector_hits = self.retriever.search_scene(ctx.norm_text, topk=self.scene_topk)
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="scene_retrieval_failed",
                    latency_ms=elapsed,
                    extra={"error": str(exc)},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="场景识别依赖暂时不可用，请稍后重试。",
                flow_type=ctx.flow_type,
                slots=dict(ctx.slots),
                options=self.recommendation_service.refuse_options(
                    ctx, OutOfScopeReason.DATA_UNAVAILABLE
                ),
                out_of_scope_reason=OutOfScopeReason.DATA_UNAVAILABLE,
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="refuse",
            )
        vector_map = self._vector_map(vector_hits, key="scene_id")

        scored: list[tuple[str, float, dict[str, float]]] = []
        for scene in scenes:
            scene_id = scene["scene_id"]
            coverage = entity_coverage_score(
                scene.get("required_slots", []),
                ctx.slots,
            )
            score_parts = {
                "rule": max(
                    keyword_overlap_score(ctx.norm_text, scene.get("keywords", [])),
                    example_similarity_score(ctx.norm_text, scene.get("examples", [])),
                ),
                "vector": vector_map.get(scene_id, 0.0),
                # 对信息不完整的站内查询给最小实体分，避免过早拒答。
                "entity": max(0.4, coverage),
            }
            final_score = weighted_score(score_parts, self.fusion_weights)
            scored.append((scene_id, final_score, score_parts))

        scored.sort(key=lambda x: x[1], reverse=True)
        top1_id, top1_score, top1_parts = scored[0] if scored else (None, 0.0, {})
        top2_score = scored[1][1] if len(scored) > 1 else 0.0

        ctx.trace.summary["scope_top1"] = top1_id
        ctx.trace.summary["vector_score"] = top1_parts.get("vector", 0.0)

        if not top1_id or top1_score < self.thresholds["T_scope"]:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="below_scope_threshold",
                    latency_ms=elapsed,
                    score=top1_score,
                    topk=[{"scene_id": sid, "score": score} for sid, score, _ in scored[:5]],
                    extra={"threshold": self.thresholds["T_scope"]},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="当前问题不在已支持的数据分析范围内。",
                flow_type=ctx.flow_type,
                slots=dict(ctx.slots),
                options=self.recommendation_service.refuse_options(
                    ctx, OutOfScopeReason.UNSUPPORTED_DOMAIN
                ),
                out_of_scope_reason=OutOfScopeReason.UNSUPPORTED_DOMAIN,
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="refuse",
            )

        if (top1_score - top2_score) < self.thresholds["T_scene_gap"]:
            elapsed = (time.perf_counter() - started) * 1000
            top_candidates = [(sid, score) for sid, score, _ in scored[:3]]
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="clarify",
                    reason="scene_ambiguous",
                    latency_ms=elapsed,
                    score=top1_score,
                    topk=[{"scene_id": sid, "score": score} for sid, score in top_candidates],
                    extra={"gap": top1_score - top2_score},
                )
            )
            return RouteDecision(
                type=DecisionType.CLARIFY,
                message="我可以继续，但需要先确认你要查询的场景。",
                flow_type=ctx.flow_type,
                slots=dict(ctx.slots),
                missing_slots=["scene"],
                options=self.recommendation_service.scene_clarify_options(top_candidates),
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="ask_slot",
            )

        elapsed = (time.perf_counter() - started) * 1000
        ctx.scene = top1_id
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="scene_in_scope",
                latency_ms=elapsed,
                score=top1_score,
                topk=[{"scene_id": sid, "score": score} for sid, score, _ in scored[:5]],
                extra={"score_parts": top1_parts},
            )
        )
        return None

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
