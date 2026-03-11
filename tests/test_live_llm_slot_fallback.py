from __future__ import annotations

import os
import time

import pytest

from template_capability.config import load_template_config
from template_capability.engine import TemplateCapabilityEngine
from template_capability.fallback import OpenAICompatibleTemplateSlotResolver


LIVE_CASES = [
    ("近24小时接口错误包告警前十", "alarm.interface.error.topn"),
    ("查询最近cpu超过八十的设备列表", "device.cpu.over.list"),
]


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1" or not os.environ.get("DASHSCOPE_API_KEY"),
    reason="requires RUN_LIVE_LLM_TESTS=1 and DASHSCOPE_API_KEY",
)


def test_live_llm_slot_fallback_improves_or_matches_baseline():
    baseline_config = load_template_config("configs/templates.json")
    llm_config = load_template_config("configs/templates.json")
    llm_config.settings.llm_slot_fallback_enabled = True

    baseline_engine = TemplateCapabilityEngine(baseline_config)
    llm_engine = TemplateCapabilityEngine(
        llm_config,
        llm_template_slot_resolver=OpenAICompatibleTemplateSlotResolver(
            api_key=os.environ["DASHSCOPE_API_KEY"],
            base_url=os.environ.get("DASHSCOPE_BASE_URL", "https://coding.dashscope.aliyuncs.com/v1"),
            model=os.environ.get("DASHSCOPE_MODEL", "qwen3-coder-plus"),
            timeout_seconds=5.0,
        ),
    )

    baseline_matched = 0
    llm_matched = 0
    llm_elapsed_values: list[float] = []

    for text, template_id in LIVE_CASES:
        baseline_payload = baseline_engine.match(text).to_dict()
        start = time.perf_counter()
        llm_payload = llm_engine.match(text).to_dict()
        wall_elapsed_ms = (time.perf_counter() - start) * 1000.0

        baseline_ok = baseline_payload["template_id"] == template_id and baseline_payload["status"] == "matched"
        llm_ok = llm_payload["template_id"] == template_id and llm_payload["status"] == "matched"
        baseline_matched += int(baseline_ok)
        llm_matched += int(llm_ok)

        selected = llm_payload.get("trace", {}).get("selected_template", {})
        slot_trace = selected.get("trace", {}).get("slot_fallback_trace", {})
        if slot_trace:
            llm_elapsed_values.append(float(slot_trace.get("elapsed_ms", wall_elapsed_ms)))

    assert llm_matched >= baseline_matched
    assert llm_matched >= 1
    if llm_elapsed_values:
        average_ms = sum(llm_elapsed_values) / len(llm_elapsed_values)
        assert average_ms < 5000.0
