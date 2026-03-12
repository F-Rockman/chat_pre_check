from __future__ import annotations

import time

from chat_pre_check.domain.enums import DecisionType
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class NL2SQLRouterMiddleware:
    """最终兜底路由：模板未命中时统一转入 NL2SQL。"""

    name = "nl2sql_router"

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        # 流水线走到这里说明：没有被 report/template/clarify/refuse 提前截断。
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="route_nl2sql",
                reason="template_not_hit",
                latency_ms=elapsed,
            )
        )
        return RouteDecision(
            type=DecisionType.ROUTE_NL2SQL,
            message="未命中模板，已路由至 NL2SQL 流程。",
            flow_type=ctx.flow_type,
            scene=ctx.scene,
            slots=dict(ctx.slots),
            missing_slots=[],
            options=[],
            clarify_round=ctx.clarify_round,
            max_clarify_round=ctx.max_clarify_round,
            next_action="route_nl2sql",
        )
