from __future__ import annotations

from chat_pre_check.application.services.slot_policy import SlotPolicyEngine
from chat_pre_check.infrastructure.config.loader import load_app_config


def test_slot_policy_prioritizes_inferable_device():
    cfg = load_app_config("configs")
    engine = SlotPolicyEngine(cfg.slot_policies)
    ranked = engine.rank_missing_slots(
        scene_id="device.query",
        missing_slots=["device_id", "region_id", "protocol"],
        slots={"intent": "trend"},
        entities={"device_candidates": [{"id": "d1"}], "region_candidates": []},
    )
    assert ranked[0].slot_name == "device_id"


def test_slot_policy_applies_when_demotes_protocol():
    cfg = load_app_config("configs")
    engine = SlotPolicyEngine(cfg.slot_policies)
    ranked = engine.rank_missing_slots(
        scene_id="alarm.query",
        missing_slots=["protocol", "region_id"],
        slots={"object_scope": "device"},
        entities={},
    )
    assert ranked[0].slot_name == "region_id"


def test_slot_policy_max_ask_per_turn():
    cfg = load_app_config("configs")
    engine = SlotPolicyEngine(cfg.slot_policies)
    ask = engine.select_slots_to_ask(
        scene_id="alarm.query",
        missing_slots=["object_scope", "time_range", "metric", "topn"],
        slots={},
        entities={},
    )
    assert len(ask) == 2
