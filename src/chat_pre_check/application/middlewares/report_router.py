from __future__ import annotations

import time

from chat_pre_check.domain.enums import DecisionType
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class ReportRouterMiddleware:
    """报告流路由器：report 流直接路由到报告执行链。"""

    name = "report_router"

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if ctx.flow_type != "report":
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="flow_not_report",
                    latency_ms=elapsed,
                )
            )
            return None

        # report 流当前采用最小闭环：一旦分流命中，直接输出报告路由结果。
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="route_report",
                reason="report_flow_selected",
                latency_ms=elapsed,
            )
        )
        return RouteDecision(
            type=DecisionType.ROUTE_REPORT,
            message="已路由至智能报告流程。",
            flow_type="report",
            scene=ctx.scene,
            slots=dict(ctx.slots),
            missing_slots=[],
            options=[],
            clarify_round=ctx.clarify_round,
            max_clarify_round=ctx.max_clarify_round,
            next_action="route_report",
        )
