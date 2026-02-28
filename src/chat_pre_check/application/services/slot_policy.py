from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SlotDecision:
    slot_name: str
    score: float
    reason: str


class SlotPolicyEngine:
    def __init__(self, policy_config: dict[str, Any] | None = None) -> None:
        self.policy_config = policy_config or {}
        self.default_cfg = self.policy_config.get("default", {})
        self.scene_cfg = self.policy_config.get("scenes", {})

    def max_ask_per_turn(self, scene_id: str) -> int:
        scene = self.scene_cfg.get(scene_id, {})
        value = scene.get("max_ask_per_turn", self.default_cfg.get("max_ask_per_turn", 2))
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 2

    def select_slots_to_ask(
        self,
        scene_id: str,
        missing_slots: list[str],
        *,
        slots: dict[str, Any],
        entities: dict[str, Any],
    ) -> list[str]:
        decisions = self.rank_missing_slots(
            scene_id=scene_id,
            missing_slots=missing_slots,
            slots=slots,
            entities=entities,
        )
        limit = self.max_ask_per_turn(scene_id)
        return [item.slot_name for item in decisions[:limit]]

    def rank_missing_slots(
        self,
        scene_id: str,
        missing_slots: list[str],
        *,
        slots: dict[str, Any],
        entities: dict[str, Any],
    ) -> list[SlotDecision]:
        ranked: list[SlotDecision] = []
        for slot_name in missing_slots:
            slot_cfg = self._slot_cfg(scene_id, slot_name)
            score = self._base_priority(slot_cfg)
            reason_parts = [f"base={score:.2f}"]

            applies_when = slot_cfg.get("applies_when", {})
            if applies_when and not self._condition_match(applies_when, slots):
                score -= 100.0
                reason_parts.append("applies_when_not_matched")
            else:
                infer_from = slot_cfg.get("infer_from", [])
                if self._has_infer_signal(infer_from, entities):
                    score += 0.4
                    reason_parts.append("infer_signal")
                if slot_cfg.get("defaultable", False):
                    score -= 0.1
                    reason_parts.append("defaultable")
                ask_cost = float(slot_cfg.get("ask_cost", 0.5))
                score -= ask_cost * 0.2
                reason_parts.append(f"ask_cost={ask_cost:.2f}")

            ranked.append(
                SlotDecision(
                    slot_name=slot_name,
                    score=score,
                    reason=";".join(reason_parts),
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _slot_cfg(self, scene_id: str, slot_name: str) -> dict[str, Any]:
        scene_slots = self.scene_cfg.get(scene_id, {}).get("slots", {})
        default_slots = self.default_cfg.get("slots", {})
        merged = {}
        merged.update(default_slots.get("*", {}))
        merged.update(default_slots.get(slot_name, {}))
        merged.update(scene_slots.get(slot_name, {}))
        return merged

    @staticmethod
    def _base_priority(slot_cfg: dict[str, Any]) -> float:
        value = slot_cfg.get("priority", 0.5)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.5

    @staticmethod
    def _condition_match(condition: dict[str, Any], slots: dict[str, Any]) -> bool:
        for key, expected in condition.items():
            actual = slots.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            else:
                if actual != expected:
                    return False
        return True

    @staticmethod
    def _has_infer_signal(infer_from: list[str], entities: dict[str, Any]) -> bool:
        if not infer_from:
            return False
        for key in infer_from:
            value = entities.get(key)
            if value:
                return True
        return False
