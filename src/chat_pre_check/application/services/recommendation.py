from __future__ import annotations

from typing import Any

from chat_pre_check.domain.enums import OutOfScopeReason
from chat_pre_check.domain.models import ActionOption, Candidate, RequestContext, SearchHit


class RecommendationService:
    """推荐服务：为拒答、澄清、范围外场景生成下一步动作。"""

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
        scene_id = ctx.scene or ctx.context_scene
        options: list[ActionOption] = []
        # 按拒答原因分层推荐，优先给“可执行下一步”而不是泛化提示。

        if reason == OutOfScopeReason.POLICY_BLOCKED:
            options.extend(self._template_options(scene_id=None, limit=2))
            options.append(ActionOption(label="我能查什么？", intent="capability.list"))
            return self._dedup_options(options, limit=limit)

        if reason == OutOfScopeReason.PERMISSION_DENIED:
            options.extend(
                self._template_options(
                    scene_id=scene_id,
                    limit=3,
                    blocked_keywords=["财务", "利润", "薪资"],
                )
            )
            options.extend(
                self._case_action_options(
                    scene_id=scene_id,
                    limit=2,
                    blocked_keywords=["财务", "利润", "薪资"],
                )
            )
            options.append(ActionOption(label="我能查什么？", intent="capability.list"))
            return self._dedup_options(options, limit=limit)

        if reason == OutOfScopeReason.OUT_OF_SEED_SCOPE:
            options.extend(self._template_options(scene_id=scene_id, limit=3))
            options.extend(self._case_action_options(scene_id=scene_id, limit=2))
            options.append(ActionOption(label="查看能力边界", intent="capability.list"))
            return self._dedup_options(options, limit=limit)

        if reason == OutOfScopeReason.DATA_UNAVAILABLE:
            options.append(ActionOption(label="稍后重试", intent=None))
            options.extend(self._template_options(scene_id=scene_id, limit=3))
            return self._dedup_options(options, limit=limit)

        if reason == OutOfScopeReason.UNKNOWN_DOMAIN:
            options.append(ActionOption(label="我能查什么？", intent="capability.list"))
            options.extend(self._template_options(scene_id=None, limit=3))
            return self._dedup_options(options, limit=limit)

        # UNSUPPORTED_DOMAIN 及其他兜底场景。
        options.extend(self._template_options(scene_id=scene_id, limit=3))
        options.extend(self._case_action_options(scene_id=scene_id, limit=2))
        options.append(ActionOption(label="我能查什么？", intent="capability.list"))
        return self._dedup_options(options, limit=limit)

    def scoped_refuse_options(
        self,
        ctx: RequestContext,
        seed_hits: list[SearchHit],
        limit: int = 4,
    ) -> list[ActionOption]:
        options: list[ActionOption] = []
        for hit in seed_hits[:limit]:
            # seed 命中用于“边界内相似能力推荐”，不直接替代当前问题执行。
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
        # 常见槽位直接给固定建议，实体槽位则优先消费解析候选。
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

    def _template_options(
        self,
        *,
        scene_id: str | None,
        limit: int,
        blocked_keywords: list[str] | None = None,
    ) -> list[ActionOption]:
        blocked = [item.lower() for item in (blocked_keywords or [])]
        # 同场景模板优先，减少用户跨域跳转成本。
        ordered_templates = sorted(
            self.templates,
            key=lambda item: (
                0
                if scene_id and str(item.get("scene_id", "")).strip() == scene_id
                else 1
            ),
        )
        options: list[ActionOption] = []
        for template in ordered_templates:
            examples = template.get("examples", [])
            if not examples:
                continue
            label = str(examples[0]).strip()
            if not label:
                continue
            lowered = label.lower()
            if blocked and any(token in lowered for token in blocked):
                continue
            options.append(
                ActionOption(
                    label=label,
                    intent=template.get("scene_id"),
                    preset_slots={},
                    need_followup_slots=[],
                )
            )
            if len(options) >= limit:
                break
        return options

    def _case_action_options(
        self,
        *,
        scene_id: str | None,
        limit: int,
        blocked_keywords: list[str] | None = None,
    ) -> list[ActionOption]:
        blocked = [item.lower() for item in (blocked_keywords or [])]
        # 从种子意图配置抽取“建议动作”，用于拒答/追问时的下一跳引导。
        ordered_cases = sorted(
            self.cases,
            key=lambda item: (
                0 if scene_id and str(item.get("scene_id", "")).strip() == scene_id else 1
            ),
        )
        options: list[ActionOption] = []
        for case in ordered_cases:
            actions = case.get("recommended_actions", [])
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                label = str(action.get("label", "查看可用能力")).strip()
                if not label:
                    continue
                lowered = label.lower()
                if blocked and any(token in lowered for token in blocked):
                    continue
                options.append(
                    ActionOption(
                        label=label,
                        intent=action.get("intent"),
                        preset_slots=action.get("preset_slots", {}),
                        need_followup_slots=action.get("need_followup_slots", []),
                    )
                )
                if len(options) >= limit:
                    return options
        return options

    @staticmethod
    def _dedup_options(options: list[ActionOption], *, limit: int) -> list[ActionOption]:
        deduped: list[ActionOption] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        # 去重键包含文案+意图+槽位值，避免推荐项语义重复。
        for option in options:
            key = (option.label, option.intent, str(option.slot_value))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(option)
            if len(deduped) >= limit:
                break
        if deduped:
            return deduped
        return [ActionOption(label="我能查什么？", intent="capability.list")]
