from __future__ import annotations

import time

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.interfaces import Resolver
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class EntityEnricherMiddleware:
    name = "entity_enricher"

    def __init__(
        self,
        device_resolver: Resolver,
        region_resolver: Resolver,
        recommendation_service: RecommendationService,
        commit_score: float,
        min_gap: float,
    ) -> None:
        self.device_resolver = device_resolver
        self.region_resolver = region_resolver
        self.recommendation_service = recommendation_service
        self.commit_score = commit_score
        self.min_gap = min_gap

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        try:
            device_candidates = self.device_resolver.resolve(ctx.norm_text, topk=3)
            region_candidates = self.region_resolver.resolve(ctx.norm_text, topk=3)
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="resolver_unavailable",
                    latency_ms=elapsed,
                    extra={"error": str(exc)},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="当前数据服务不可用，请稍后重试。",
                slots=dict(ctx.slots),
                options=self.recommendation_service.refuse_options(
                    ctx, OutOfScopeReason.DATA_UNAVAILABLE
                ),
                out_of_scope_reason=OutOfScopeReason.DATA_UNAVAILABLE,
            )

        ctx.entities["device_candidates"] = device_candidates
        ctx.entities["region_candidates"] = region_candidates
        self._commit_slot("device_id", device_candidates, ctx)
        self._commit_slot("region_id", region_candidates, ctx)

        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="entity_enriched",
                latency_ms=elapsed,
                extra={
                    "device_candidates": len(device_candidates),
                    "region_candidates": len(region_candidates),
                },
            )
        )
        return None

    def _commit_slot(self, slot_name: str, candidates: list, ctx: RequestContext) -> None:
        if not candidates:
            return
        top1 = candidates[0]
        top2 = candidates[1] if len(candidates) > 1 else None
        gap = top1.score - top2.score if top2 else top1.score
        if top1.score >= self.commit_score and gap >= self.min_gap:
            ctx.slots[slot_name] = top1.entity_id
