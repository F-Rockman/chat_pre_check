from __future__ import annotations

import time

from chat_pre_check.application.pipeline import MiddlewarePipeline
from chat_pre_check.application.services.trace import render_trace
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.models import ActionOption, RequestContext, RouteDecision, RouteRequest
from chat_pre_check.domain.models import TraceStep


class PrecheckEngine:
    def __init__(
        self,
        pipeline: MiddlewarePipeline,
        *,
        fallback_options: list[ActionOption] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.fallback_options = fallback_options or [
            ActionOption(label="查近24小时全网告警", intent="alarm.query"),
            ActionOption(label="查昨天华东离线设备数", intent="device.query"),
            ActionOption(label="我能查什么？", intent="capability.list"),
        ]

    def route(self, request: RouteRequest) -> RouteDecision:
        ctx = RequestContext(
            input_text=request.input_text,
            tenant_id=request.tenant_id,
            role=request.role,
            context_scene=(request.context or {}).get("scene"),
            slots=dict((request.context or {}).get("slots", {})),
            trace_level=request.trace_level,
        )
        started = time.perf_counter()
        try:
            decision = self.pipeline.run(ctx)
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step="engine",
                    decision="refuse",
                    reason="pipeline_exception",
                    latency_ms=elapsed,
                    extra={"error": str(exc)},
                )
            )
            decision = RouteDecision(
                type=DecisionType.REFUSE,
                message="系统繁忙或依赖暂时不可用，请稍后重试。",
                slots=dict(ctx.slots),
                options=list(self.fallback_options),
                out_of_scope_reason=OutOfScopeReason.DATA_UNAVAILABLE,
            )
        decision.trace = render_trace(ctx.trace, level=request.trace_level)
        if not decision.scene:
            decision.scene = ctx.scene
        if not decision.slots:
            decision.slots = dict(ctx.slots)
        return decision
