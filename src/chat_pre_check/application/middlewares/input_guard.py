from __future__ import annotations

import time

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class InputGuardMiddleware:
    """输入边界守卫：拦截空输入和超长输入。"""

    name = "input_guard"

    def __init__(
        self,
        recommendation_service: RecommendationService,
        *,
        max_input_chars: int = 1000,
        min_input_chars: int = 1,
    ) -> None:
        self.recommendation_service = recommendation_service
        self.max_input_chars = max_input_chars
        self.min_input_chars = min_input_chars

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        raw = (ctx.input_text or "").strip()
        norm = (ctx.norm_text or "").strip()

        # 空输入走澄清，避免无意义下游处理。
        if len(raw) < self.min_input_chars or len(norm) < self.min_input_chars:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="clarify",
                    reason="empty_input",
                    latency_ms=elapsed,
                )
            )
            return RouteDecision(
                type=DecisionType.CLARIFY,
                message="我没收到有效问题，请用一句话描述你要查询的网络运维问题。",
                slots=dict(ctx.slots),
                missing_slots=["input_text"],
                options=self.recommendation_service.refuse_options(
                    ctx, OutOfScopeReason.UNKNOWN_DOMAIN
                ),
            )

        # 超长输入直接拒答，降低误召回和异常解析成本。
        if len(raw) > self.max_input_chars:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="input_too_long",
                    latency_ms=elapsed,
                    extra={"max_input_chars": self.max_input_chars, "actual": len(raw)},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message=f"输入过长（>{self.max_input_chars} 字），请拆分为更具体的查询。",
                slots=dict(ctx.slots),
                options=self.recommendation_service.refuse_options(
                    ctx, OutOfScopeReason.UNSUPPORTED_DOMAIN
                ),
                out_of_scope_reason=OutOfScopeReason.UNSUPPORTED_DOMAIN,
            )

        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="input_valid",
                latency_ms=elapsed,
                extra={"length": len(raw)},
            )
        )
        return None
