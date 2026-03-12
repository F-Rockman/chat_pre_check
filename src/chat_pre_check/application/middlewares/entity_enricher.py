from __future__ import annotations

import time

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.interfaces import Resolver
from chat_pre_check.domain.models import Candidate
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class EntityEnricherMiddleware:
    """远程解析增强：补充设备/区域候选并按阈值自动落槽。"""

    name = "entity_enricher"

    def __init__(
        self,
        device_resolver: Resolver,
        region_resolver: Resolver,
        recommendation_service: RecommendationService,
        commit_score: float,
        min_gap: float,
        skip_resolver_when_prefilled: bool = True,
    ) -> None:
        self.device_resolver = device_resolver
        self.region_resolver = region_resolver
        self.recommendation_service = recommendation_service
        self.commit_score = commit_score
        self.min_gap = min_gap
        self.skip_resolver_when_prefilled = skip_resolver_when_prefilled

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        # 若 AC 预提参已给出候选，可按配置跳过远程 resolver，降低时延与依赖风险。
        prefilled_device = self._normalize_candidates(ctx.entities.get("device_candidates", []))
        prefilled_region = self._normalize_candidates(ctx.entities.get("region_candidates", []))

        device_candidates = list(prefilled_device)
        region_candidates = list(prefilled_region)
        resolver_errors: dict[str, str] = {}

        if not (self.skip_resolver_when_prefilled and prefilled_device):
            try:
                resolved = self.device_resolver.resolve(ctx.norm_text, topk=3)
                device_candidates = self._merge_candidates(device_candidates, resolved)
            except Exception as exc:
                resolver_errors["device"] = str(exc)

        if not (self.skip_resolver_when_prefilled and prefilled_region):
            try:
                resolved = self.region_resolver.resolve(ctx.norm_text, topk=3)
                region_candidates = self._merge_candidates(region_candidates, resolved)
            except Exception as exc:
                resolver_errors["region"] = str(exc)

        if resolver_errors and not self._has_prefill_fallback(ctx, device_candidates, region_candidates):
            # 远程解析失败且本地无可用候选时，统一走数据不可用拒答。
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="resolver_unavailable",
                    latency_ms=elapsed,
                    extra={"error": resolver_errors},
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
        # resolver 只在高置信时自动落槽，其余情况交给追问或模板校验。
        self._commit_slot("device_id", device_candidates, ctx)
        self._commit_slot("region_id", region_candidates, ctx)

        elapsed = (time.perf_counter() - started) * 1000
        reason = "entity_enriched"
        if resolver_errors:
            reason = "entity_enriched_with_prefill_fallback"
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason=reason,
                latency_ms=elapsed,
                extra={
                    "device_candidates": len(device_candidates),
                    "region_candidates": len(region_candidates),
                    "resolver_errors": resolver_errors,
                },
            )
        )
        return None

    def _commit_slot(self, slot_name: str, candidates: list, ctx: RequestContext) -> None:
        # 仅在 top1 分数和 top1-top2 gap 同时达标时自动提交，避免误填。
        if ctx.slots.get(slot_name) not in (None, ""):
            return
        if not candidates:
            return
        top1 = candidates[0]
        top2 = candidates[1] if len(candidates) > 1 else None
        gap = top1.score - top2.score if top2 else top1.score
        if top1.score >= self.commit_score and gap >= self.min_gap:
            ctx.slots[slot_name] = top1.entity_id

    @staticmethod
    def _normalize_candidates(candidates: list) -> list[Candidate]:
        if not isinstance(candidates, list):
            return []
        return [item for item in candidates if isinstance(item, Candidate)]

    @staticmethod
    def _merge_candidates(current: list[Candidate], incoming: list[Candidate]) -> list[Candidate]:
        merged: dict[str, Candidate] = {}
        for item in current + incoming:
            entity_id = str(item.entity_id)
            if not entity_id:
                continue
            prev = merged.get(entity_id)
            if prev is None or item.score > prev.score:
                merged[entity_id] = item
        ranked = list(merged.values())
        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked

    @staticmethod
    def _has_prefill_fallback(
        ctx: RequestContext, device_candidates: list[Candidate], region_candidates: list[Candidate]
    ) -> bool:
        if device_candidates or region_candidates:
            return True
        if ctx.slots.get("device_id") not in (None, ""):
            return True
        if ctx.slots.get("region_id") not in (None, ""):
            return True
        return False
