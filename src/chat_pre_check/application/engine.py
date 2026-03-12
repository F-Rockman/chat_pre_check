from __future__ import annotations

import time

from chat_pre_check.application.pipeline import MiddlewarePipeline
from chat_pre_check.application.services.trace import render_trace
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.models import ActionOption, RequestContext, RouteDecision, RouteRequest
from chat_pre_check.domain.models import TraceStep


class PrecheckEngine:
    """路由引擎入口：构造请求上下文，执行中间件流水线并兜底异常。"""

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
        # 将外部请求字段投影到内部上下文，统一后续链路读取方式。
        context = request.context or {}
        clarify_round = context.get("clarify_round", 0)
        max_clarify_round = context.get("max_clarify_round", 5)
        try:
            clarify_round = max(0, int(clarify_round))
        except (TypeError, ValueError):
            clarify_round = 0
        try:
            max_clarify_round = max(1, int(max_clarify_round))
        except (TypeError, ValueError):
            max_clarify_round = 5

        ctx = RequestContext(
            input_text=request.input_text,
            tenant_id=request.tenant_id,
            role=request.role,
            context_scene=context.get("scene"),
            context_flow_type=context.get("flow_type"),
            route_override=context.get("route_override"),
            slots=dict(context.get("slots", {})),
            pending_slots=list(context.get("pending_slots", []))
            if isinstance(context.get("pending_slots"), list)
            else [],
            clarify_round=clarify_round,
            max_clarify_round=max_clarify_round,
            trace_level=request.trace_level,
        )
        started = time.perf_counter()
        try:
            decision = self.pipeline.run(ctx)
        except Exception as exc:
            # 任一中间件异常都收敛为可观测的拒答结果，避免直接抛 500。
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
                flow_type=ctx.flow_type or ctx.context_flow_type,
                slots=dict(ctx.slots),
                options=list(self.fallback_options),
                out_of_scope_reason=OutOfScopeReason.DATA_UNAVAILABLE,
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="refuse",
            )
        # trace 最后统一渲染，保证成功/失败路径都带上完整观测信息。
        decision.trace = render_trace(ctx.trace, level=request.trace_level)
        # 补全兜底字段，确保响应结构稳定。
        if not decision.scene:
            decision.scene = ctx.scene
        if not decision.flow_type:
            decision.flow_type = ctx.flow_type or ctx.context_flow_type
        if not decision.slots:
            decision.slots = dict(ctx.slots)
        if decision.clarify_round is None:
            decision.clarify_round = ctx.clarify_round
        if decision.max_clarify_round is None:
            decision.max_clarify_round = ctx.max_clarify_round
        return decision
