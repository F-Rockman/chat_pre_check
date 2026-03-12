from __future__ import annotations

import time
from typing import Any

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.interfaces import Retriever
from chat_pre_check.domain.models import RequestContext, RouteDecision, SearchHit, TraceStep


class SeedScopeGuardMiddleware:
    """Seed 能力边界守卫：控制 NL2SQL 兜底是否放行。"""

    name = "seed_scope_guard"

    def __init__(
        self,
        retriever: Retriever,
        recommendation_service: RecommendationService,
        guard_config: dict[str, Any] | None = None,
    ) -> None:
        self.retriever = retriever
        self.recommendation_service = recommendation_service
        self.guard_config = guard_config or {}

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if ctx.flow_type and ctx.flow_type != "query":
            # 只有 query -> NL2SQL 兜底路径需要做 seed 边界保护。
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="non_query_flow_skip",
                    latency_ms=elapsed,
                )
            )
            return None

        if not self.guard_config.get("enabled", False):
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="guard_disabled",
                    latency_ms=elapsed,
                )
            )
            return None

        try:
            seed_hits = self.retriever.search_seed_cases(
                ctx.norm_text, topk=int(self.guard_config.get("topk", 5))
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="seed_retrieval_failed",
                    latency_ms=elapsed,
                    extra={"error": str(exc)},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="能力边界检查依赖不可用，请稍后重试。",
                flow_type=ctx.flow_type,
                scene=ctx.scene,
                slots=dict(ctx.slots),
                options=self.recommendation_service.refuse_options(
                    ctx, OutOfScopeReason.DATA_UNAVAILABLE
                ),
                out_of_scope_reason=OutOfScopeReason.DATA_UNAVAILABLE,
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="refuse",
            )

        score = seed_hits[0].score if seed_hits else 0.0
        min_score = float(self.guard_config.get("min_score", 0.55))
        min_hits = int(self.guard_config.get("min_hits", 1))
        allowed_scenes = self.guard_config.get("allowed_scenes", [])

        ctx.trace.summary["seed_scope_score"] = score
        ctx.trace.summary["seed_scope_top_case"] = (
            seed_hits[0].metadata.get("case_id") if seed_hits else None
        )

        if allowed_scenes and ctx.scene and ctx.scene not in allowed_scenes:
            # 某些场景即使有 seed 命中，也可以通过配置禁止走 NL2SQL。
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="scene_not_allowed_by_seed_guard",
                    latency_ms=elapsed,
                    extra={"scene": ctx.scene, "allowed_scenes": allowed_scenes},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="当前场景尚未开放 NL2SQL 能力，请选择已支持的查询入口。",
                flow_type=ctx.flow_type,
                scene=ctx.scene,
                slots=dict(ctx.slots),
                options=self.recommendation_service.scoped_refuse_options(ctx, seed_hits),
                out_of_scope_reason=OutOfScopeReason.OUT_OF_SEED_SCOPE,
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="refuse",
            )

        if len(seed_hits) < min_hits or score < min_score:
            # 命中数量或相似度不达标时拒绝 NL2SQL，返回边界内替代建议。
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="below_seed_scope_threshold",
                    latency_ms=elapsed,
                    score=score,
                    topk=[
                        {
                            "case_id": hit.metadata.get("case_id"),
                            "score": hit.score,
                        }
                        for hit in seed_hits[:5]
                    ],
                    extra={"min_score": min_score, "min_hits": min_hits},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="该问题暂超出当前可支持的 NL2SQL 能力范围。",
                flow_type=ctx.flow_type,
                scene=ctx.scene,
                slots=dict(ctx.slots),
                options=self.recommendation_service.scoped_refuse_options(ctx, seed_hits),
                out_of_scope_reason=OutOfScopeReason.OUT_OF_SEED_SCOPE,
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="refuse",
            )

        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="within_seed_scope",
                latency_ms=elapsed,
                score=score,
                topk=[
                    {
                        "case_id": hit.metadata.get("case_id"),
                        "score": hit.score,
                    }
                    for hit in seed_hits[:5]
                ],
            )
        )
        return None
