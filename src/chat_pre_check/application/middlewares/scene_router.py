from __future__ import annotations

import time

from chat_pre_check.domain.interfaces import SceneRepository
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class SceneRouterMiddleware:
    name = "scene_router"

    def __init__(self, scene_repository: SceneRepository) -> None:
        self.scene_repository = scene_repository

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if ctx.context_scene:
            if self.scene_repository.get(ctx.context_scene):
                ctx.scene = ctx.context_scene
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="scene_selected" if ctx.scene else "scene_pending",
                latency_ms=elapsed,
                extra={"scene": ctx.scene},
            )
        )
        return None
