from __future__ import annotations

from typing import Any

from chat_pre_check.domain.enums import OutOfScopeReason
from chat_pre_check.domain.models import ActionOption, Candidate, RequestContext, SearchHit


class RecommendationService:
    def __init__(
        self,
        scenes: list[dict[str, Any]],
        templates: list[dict[str, Any]],
        cases: list[dict[str, Any]],
    ) -> None:
        self.scenes = scenes
        self.templates = templates
        self.cases = cases

    def refuse_options(
        self, ctx: RequestContext, reason: OutOfScopeReason, limit: int = 4
    ) -> list[ActionOption]:
        options: list[ActionOption] = []
        for template in self.templates:
            examples = template.get("examples", [])
            if not examples:
                continue
            options.append(
                ActionOption(
                    label=examples[0],
                    intent=template.get("scene_id"),
                    preset_slots={},
                    need_followup_slots=[],
                )
            )
            if len(options) >= limit:
                return options

        for case in self.cases:
            actions = case.get("recommended_actions", [])
            for action in actions:
                options.append(
                    ActionOption(
                        label=action.get("label", "查看可用能力"),
                        intent=action.get("intent"),
                        preset_slots=action.get("preset_slots", {}),
                        need_followup_slots=action.get("need_followup_slots", []),
                    )
                )
                if len(options) >= limit:
                    return options

        options.append(
            ActionOption(
                label="我能查什么？",
                intent="capability.list",
                preset_slots={},
                need_followup_slots=[],
            )
        )
        return options[:limit]

    def scoped_refuse_options(
        self,
        ctx: RequestContext,
        seed_hits: list[SearchHit],
        limit: int = 4,
    ) -> list[ActionOption]:
        options: list[ActionOption] = []
        for hit in seed_hits[:limit]:
            label = str(hit.metadata.get("label", "相似能力查询"))
            case_id = hit.metadata.get("case_id")
            preset_slots = {}
            if hit.metadata.get("scene_id"):
                preset_slots["scene"] = hit.metadata["scene_id"]
            options.append(
                ActionOption(
                    label=label,
                    intent="seed_case",
                    preset_slots=preset_slots,
                    need_followup_slots=[],
                    slot_value=case_id,
                )
            )
        if options:
            return options
        return self.refuse_options(ctx, OutOfScopeReason.OUT_OF_SEED_SCOPE, limit=limit)

    def scene_clarify_options(
        self, scene_candidates: list[tuple[str, float]], limit: int = 3
    ) -> list[ActionOption]:
        options = []
        for scene_id, _score in scene_candidates[:limit]:
            options.append(
                ActionOption(
                    label=f"按 {scene_id} 查询",
                    intent=scene_id,
                    preset_slots={"scene": scene_id},
                    need_followup_slots=[],
                )
            )
        return options

    def slot_clarify_options(
        self,
        missing_slot: str,
        ctx: RequestContext,
        candidate_limit: int = 3,
    ) -> list[ActionOption]:
        if missing_slot == "time_range":
            return [
                ActionOption(
                    label="近24小时",
                    preset_slots={"time_range": "last_24h"},
                ),
                ActionOption(
                    label="近7天",
                    preset_slots={"time_range": "last_7d"},
                ),
                ActionOption(
                    label="今天",
                    preset_slots={"time_range": "today"},
                ),
            ]

        if missing_slot == "object_scope":
            return [
                ActionOption(
                    label="全网告警（近24小时）",
                    preset_slots={"object_scope": "network", "time_range": "last_24h"},
                ),
                ActionOption(
                    label="设备告警（近24小时）",
                    preset_slots={"object_scope": "device", "time_range": "last_24h"},
                ),
                ActionOption(
                    label="端口告警（近24小时）",
                    preset_slots={"object_scope": "port", "time_range": "last_24h"},
                ),
            ]

        if missing_slot == "device_id":
            return self._candidate_options(
                ctx.entities.get("device_candidates", []),
                slot_name="device_id",
                candidate_limit=candidate_limit,
            )

        if missing_slot == "region_id":
            return self._candidate_options(
                ctx.entities.get("region_candidates", []),
                slot_name="region_id",
                candidate_limit=candidate_limit,
            )

        if missing_slot == "metric":
            return [
                ActionOption(label="丢包率", preset_slots={"metric": "packet_loss"}),
                ActionOption(label="时延", preset_slots={"metric": "latency"}),
                ActionOption(label="CPU 使用率", preset_slots={"metric": "cpu_usage"}),
            ]

        if missing_slot == "protocol":
            return [
                ActionOption(label="BGP", preset_slots={"protocol": "bgp"}),
                ActionOption(label="OSPF", preset_slots={"protocol": "ospf"}),
                ActionOption(label="ISIS", preset_slots={"protocol": "isis"}),
            ]

        if missing_slot == "topn":
            return [
                ActionOption(label="Top5", preset_slots={"topn": 5}),
                ActionOption(label="Top10", preset_slots={"topn": 10}),
                ActionOption(label="Top20", preset_slots={"topn": 20}),
            ]

        return [
            ActionOption(
                label=f"补充 {missing_slot}",
                need_followup_slots=[missing_slot],
            )
        ]

    def _candidate_options(
        self,
        candidates: list[Candidate],
        slot_name: str,
        candidate_limit: int,
    ) -> list[ActionOption]:
        if not candidates:
            return [ActionOption(label=f"请提供 {slot_name}", need_followup_slots=[slot_name])]
        options: list[ActionOption] = []
        for candidate in candidates[:candidate_limit]:
            options.append(
                ActionOption(
                    label=candidate.name,
                    preset_slots={slot_name: candidate.entity_id},
                    slot_value=candidate.entity_id,
                )
            )
        return options
