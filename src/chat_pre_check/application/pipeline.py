from __future__ import annotations

from chat_pre_check.domain.interfaces import Middleware
from chat_pre_check.domain.models import RequestContext, RouteDecision


class MiddlewarePipeline:
    """顺序执行中间件；遇到首个决策即短路返回。"""

    def __init__(self, middlewares: list[Middleware]) -> None:
        self.middlewares = middlewares

    def run(self, ctx: RequestContext) -> RouteDecision:
        # 中间件按既定顺序执行；谁先返回 RouteDecision，谁就终止链路。
        for middleware in self.middlewares:
            try:
                decision = middleware.process(ctx)
            except Exception as exc:
                # 标准化中间件异常信息，便于定位失败环节。
                middleware_name = getattr(middleware, "name", middleware.__class__.__name__)
                raise RuntimeError(
                    f"middleware_failed:{middleware_name}:{exc}"
                ) from exc
            if decision is not None:
                return decision
        # 正常情况下最后一定会落到 report/template/nl2sql 之一。
        raise RuntimeError("Pipeline finished without a route decision.")
