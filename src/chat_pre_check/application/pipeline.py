from __future__ import annotations

from chat_pre_check.domain.interfaces import Middleware
from chat_pre_check.domain.models import RequestContext, RouteDecision


class MiddlewarePipeline:
    def __init__(self, middlewares: list[Middleware]) -> None:
        self.middlewares = middlewares

    def run(self, ctx: RequestContext) -> RouteDecision:
        for middleware in self.middlewares:
            try:
                decision = middleware.process(ctx)
            except Exception as exc:
                middleware_name = getattr(middleware, "name", middleware.__class__.__name__)
                raise RuntimeError(
                    f"middleware_failed:{middleware_name}:{exc}"
                ) from exc
            if decision is not None:
                return decision
        raise RuntimeError("Pipeline finished without a route decision.")
