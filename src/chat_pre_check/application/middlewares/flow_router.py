from __future__ import annotations

import time
from typing import Any

from chat_pre_check.application.services.llm_assist import FlowLLMAssistService
from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.application.services.scoring import example_similarity_score, keyword_overlap_score
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.interfaces import SceneRepository
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class FlowRouterMiddleware:
    """业务流分流：query/report/direct/unknown。"""

    name = "flow_router"
    VALID_FLOWS = {"query", "report", "direct", "unknown"}

    def __init__(
        self,
        *,
        scene_repository: SceneRepository,
        recommendation_service: RecommendationService,
        router_config: dict[str, Any] | None = None,
        llm_assist: FlowLLMAssistService | None = None,
    ) -> None:
        cfg = router_config or {}
        self.scene_repository = scene_repository
        self.recommendation_service = recommendation_service
        self.enabled = bool(cfg.get("enabled", True))
        self.min_confidence = float(cfg.get("min_confidence", 0.30))
        self.ambiguous_gap = float(cfg.get("ambiguous_gap", 0.08))
        self.llm_on_low_confidence = bool(cfg.get("llm_on_low_confidence", False))
        self.allow_direct_pass = bool(cfg.get("allow_direct_pass", False))
        self.direct_pass_intents = [str(item).strip().lower() for item in cfg.get("direct_pass_intents", [])]
        self.llm_assist = llm_assist

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if not self.enabled:
            return self._continue(ctx, started, reason="flow_router_disabled")

        if ctx.route_override and str(ctx.route_override).strip().lower() in self.VALID_FLOWS:
            ctx.flow_type = str(ctx.route_override).strip().lower()
            return self._continue(
                ctx,
                started,
                reason="route_override",
                extra={"flow_type": ctx.flow_type},
            )

        if ctx.context_flow_type and str(ctx.context_flow_type).strip().lower() in self.VALID_FLOWS:
            ctx.flow_type = str(ctx.context_flow_type).strip().lower()
            return self._continue(
                ctx,
                started,
                reason="context_flow_override",
                extra={"flow_type": ctx.flow_type},
            )

        text = ctx.norm_text
        if self.allow_direct_pass and any(token and token in text for token in self.direct_pass_intents):
            ctx.flow_type = "direct"
            return self._continue(
                ctx,
                started,
                reason="direct_pass",
                extra={"flow_type": ctx.flow_type},
            )

        flow_scores, scene_scores = self._score_flows(text)
        selected_flow, selected_score = ("unknown", 0.0)
        second_score = 0.0
        if flow_scores:
            selected_flow, selected_score = flow_scores[0]
            second_score = flow_scores[1][1] if len(flow_scores) > 1 else 0.0

        llm_used = False
        llm_error: str | None = None
        if self._should_use_llm(selected_score, second_score) and self.llm_assist and ctx.llm_calls < 1:
            ctx.llm_calls += 1
            llm_result = None
            try:
                llm_result = self.llm_assist.infer_flow(
                    input_text=ctx.input_text,
                    flow_candidates=flow_scores[:2],
                    scene_candidates=scene_scores[:3],
                    slots=ctx.slots,
                )
            except Exception as exc:  # pragma: no cover - network dependent
                llm_error = str(exc)[:240]
                ctx.trace.summary["llm_error"] = llm_error
            if llm_result is not None and llm_result.flow_type in self.VALID_FLOWS:
                selected_flow = llm_result.flow_type
                selected_score = max(selected_score, llm_result.confidence)
                if llm_result.scene and self.scene_repository.get(llm_result.scene):
                    ctx.entities["llm_scene_hint"] = llm_result.scene
                for key, value in llm_result.slots.items():
                    if key not in ctx.slots or ctx.slots.get(key) in (None, ""):
                        ctx.slots[key] = value
                llm_used = True
                ctx.trace.summary["llm_latency_ms"] = llm_result.latency_ms

        if selected_flow == "unknown" or selected_score <= 0.0:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="refuse",
                    reason="flow_unknown",
                    latency_ms=elapsed,
                    score=selected_score,
                    topk=[{"flow_type": flow, "score": score} for flow, score in flow_scores[:4]],
                    extra={"llm_used": llm_used, "llm_error": llm_error},
                )
            )
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="当前问题暂无法分流到已支持能力，请换一种问法。",
                flow_type="unknown",
                scene=ctx.scene,
                slots=dict(ctx.slots),
                options=self.recommendation_service.refuse_options(ctx, OutOfScopeReason.UNKNOWN_DOMAIN),
                out_of_scope_reason=OutOfScopeReason.UNKNOWN_DOMAIN,
                clarify_round=ctx.clarify_round,
                max_clarify_round=ctx.max_clarify_round,
                next_action="refuse",
            )

        ctx.flow_type = selected_flow
        ctx.trace.summary["flow_type"] = ctx.flow_type
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="flow_selected",
                latency_ms=elapsed,
                score=selected_score,
                topk=[{"flow_type": flow, "score": score} for flow, score in flow_scores[:4]],
                extra={"flow_type": ctx.flow_type, "llm_used": llm_used, "llm_error": llm_error},
            )
        )
        return None

    def _score_flows(self, text: str) -> tuple[list[tuple[str, float]], list[tuple[str, float, str]]]:
        flow_best: dict[str, float] = {}
        scene_scores: list[tuple[str, float, str]] = []
        for scene in self.scene_repository.all_enabled():
            scene_id = str(scene.get("scene_id", "")).strip()
            if not scene_id:
                continue
            flow_type = str(scene.get("flow_type", "query")).strip().lower() or "query"
            if flow_type not in self.VALID_FLOWS:
                flow_type = "query"
            keyword_score = keyword_overlap_score(text, scene.get("keywords", []))
            example_score = example_similarity_score(text, scene.get("examples", []))
            entry_score = self._entry_phrase_score(text, scene.get("entry_phrases", []))
            score = max(keyword_score, example_score, entry_score)
            scene_scores.append((scene_id, score, flow_type))
            flow_best[flow_type] = max(flow_best.get(flow_type, 0.0), score)
        flow_scores = sorted(flow_best.items(), key=lambda item: item[1], reverse=True)
        scene_scores.sort(key=lambda item: item[1], reverse=True)
        return flow_scores, scene_scores

    @staticmethod
    def _entry_phrase_score(text: str, entry_phrases: list[str]) -> float:
        if not isinstance(entry_phrases, list) or not entry_phrases:
            return 0.0
        hits = 0
        for phrase in entry_phrases:
            token = str(phrase).strip().lower()
            if token and token in text:
                hits += 1
        if hits <= 0:
            return 0.0
        return min(1.0, 0.4 + hits * 0.2)

    def _should_use_llm(self, top1: float, top2: float) -> bool:
        if not self.llm_assist or not self.llm_assist.enabled:
            return False
        if top1 <= 0.0:
            return False
        if top1 < self.min_confidence:
            return self.llm_on_low_confidence
        return (top1 - top2) < self.ambiguous_gap

    def _continue(
        self,
        ctx: RequestContext,
        started: float,
        *,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> RouteDecision | None:
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason=reason,
                latency_ms=elapsed,
                extra=extra or {},
            )
        )
        return None
