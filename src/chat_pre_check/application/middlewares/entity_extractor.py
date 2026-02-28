from __future__ import annotations

import time
from typing import Any

from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep
from chat_pre_check.infrastructure.extractors.rule_extractors import extract_entities


class EntityExtractorMiddleware:
    name = "entity_extractor"

    def __init__(self, default_timezone: str) -> None:
        self.default_timezone = default_timezone

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        entities = extract_entities(ctx.norm_text, timezone=self.default_timezone)
        ctx.entities.update(entities)
        self._merge_slots(ctx, entities)
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="entity_extracted",
                latency_ms=elapsed,
                extra={"keys": sorted(list(entities.keys()))},
            )
        )
        return None

    @staticmethod
    def _merge_slots(ctx: RequestContext, entities: dict[str, Any]) -> None:
        if entities.get("time_range"):
            ctx.slots["time_range"] = entities["time_range"]
        if entities.get("topn") is not None:
            ctx.slots["topn"] = entities["topn"]
        if entities.get("severity"):
            ctx.slots["severity"] = entities["severity"]
        if entities.get("alarm_status"):
            ctx.slots["alarm_status"] = entities["alarm_status"]
        if entities.get("object_scope"):
            ctx.slots["object_scope"] = entities["object_scope"]
        if entities.get("device_ip"):
            ctx.slots["device_ip"] = entities["device_ip"]
        if entities.get("region_hint"):
            ctx.slots["region_hint"] = entities["region_hint"]
        if entities.get("intent"):
            ctx.slots["intent"] = entities["intent"]
        if entities.get("metric"):
            ctx.slots["metric"] = entities["metric"]
        if entities.get("protocol"):
            ctx.slots["protocol"] = entities["protocol"]
        if entities.get("threshold_percent") is not None:
            ctx.slots["threshold_percent"] = entities["threshold_percent"]
