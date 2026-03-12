from __future__ import annotations

import time

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.application.services.slot_policy import SlotPolicyEngine
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.interfaces import SceneRepository
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class SlotClarifierMiddleware:
    """槽位澄清器：补默认值、计算缺槽位、生成追问选项。"""

    name = "slot_clarifier"

    def __init__(
        self,
        scene_repository: SceneRepository,
        recommendation_service: RecommendationService,
        slot_policy_engine: SlotPolicyEngine,
        max_rounds: int = 5,
    ) -> None:
        self.scene_repository = scene_repository
        self.recommendation_service = recommendation_service
        self.slot_policy_engine = slot_policy_engine
        self.max_rounds = max(1, int(max_rounds))

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if not ctx.scene:
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="continue",
                    reason="scene_absent_skip",
                    latency_ms=elapsed,
                )
            )
            return None

        scene = self.scene_repository.get(ctx.scene) or {}
        defaults = scene.get("defaults", {})
        for slot_name, default_value in defaults.items():
            # 默认值只填补空槽位，不覆盖显式用户输入。
            if ctx.slots.get(slot_name) in (None, ""):
                ctx.slots[slot_name] = default_value

        required_slots = list(scene.get("required_slots", []))
        # 条件必填：根据已填槽位动态扩展 required_slots。
        for condition in scene.get("conditional_slots", []):
            slot_name = condition.get("if_slot")
            expected = condition.get("equals")
            if slot_name and ctx.slots.get(slot_name) == expected:
                required_slots.extend(condition.get("required_slots", []))
        required_slots = list(dict.fromkeys(required_slots))
        missing = [slot for slot in required_slots if ctx.slots.get(slot) in (None, "")]
        ranked = self.slot_policy_engine.rank_missing_slots(
            scene_id=ctx.scene,
            missing_slots=missing,
            slots=ctx.slots,
            entities=ctx.entities,
        )

        if missing:
            # 多缺口场景按策略引擎排序，只询问本轮最关键槽位。
            ask_slots = self.slot_policy_engine.select_slots_to_ask(
                scene_id=ctx.scene,
                missing_slots=missing,
                slots=ctx.slots,
                entities=ctx.entities,
            )
            primary = ask_slots[0]
            max_rounds = max(1, int(ctx.max_clarify_round or self.max_rounds))
            if ctx.clarify_round >= max_rounds:
                elapsed = (time.perf_counter() - started) * 1000
                ctx.trace.add_step(
                    TraceStep(
                        step=self.name,
                        decision="refuse",
                        reason="clarify_round_exceeded",
                        latency_ms=elapsed,
                        extra={
                            "clarify_round": ctx.clarify_round,
                            "max_rounds": max_rounds,
                            "missing_slots": missing,
                        },
                    )
                )
                return RouteDecision(
                    type=DecisionType.REFUSE,
                    message="已达到最大追问轮次，请补充完整条件后重试。",
                    flow_type=ctx.flow_type,
                    scene=ctx.scene,
                    slots=dict(ctx.slots),
                    options=self.recommendation_service.refuse_options(
                        ctx, OutOfScopeReason.UNSUPPORTED_DOMAIN
                    ),
                    out_of_scope_reason=OutOfScopeReason.UNSUPPORTED_DOMAIN,
                    clarify_round=ctx.clarify_round,
                    max_clarify_round=max_rounds,
                    next_action="refuse",
                )

            ctx.clarify_round += 1
            # pending_slots 记录“本轮打算问什么”，便于多轮对话续接。
            ctx.pending_slots = list(ask_slots)
            elapsed = (time.perf_counter() - started) * 1000
            ctx.trace.add_step(
                TraceStep(
                    step=self.name,
                    decision="clarify",
                    reason="required_slots_missing",
                    latency_ms=elapsed,
                    extra={
                        "missing_slots": missing,
                        "ranked_slots": [
                            {
                                "slot_name": item.slot_name,
                                "score": item.score,
                                "reason": item.reason,
                            }
                            for item in ranked
                        ],
                        "clarify_round": ctx.clarify_round,
                        "max_rounds": max_rounds,
                    },
                )
            )
            return RouteDecision(
                type=DecisionType.CLARIFY,
                message=f"继续前需要先确认：{primary}。",
                flow_type=ctx.flow_type,
                scene=ctx.scene,
                slots=dict(ctx.slots),
                missing_slots=ask_slots,
                options=self.recommendation_service.slot_clarify_options(primary, ctx),
                clarify_round=ctx.clarify_round,
                max_clarify_round=max_rounds,
                next_action="ask_slot",
            )

        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="slots_complete",
                latency_ms=elapsed,
            )
        )
        return None
