from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from template_capability.config import load_template_config
from template_capability.engine import TemplateCapabilityEngine
from template_capability.fallback import OpenAICompatibleTemplateSlotResolver


DEFAULT_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
DEFAULT_MODEL = "qwen3-coder-plus"
DEFAULT_CASES = [
    {
        "text": "近24小时接口错误包告警前十",
        "template_id": "alarm.interface.error.topn",
    },
    {
        "text": "近7天各区域丢包率排名前五",
        "template_id": "network.packet_loss.rank.topn",
    },
    {
        "text": "查询最近cpu超过八十的设备列表",
        "template_id": "device.cpu.over.list",
    },
    {
        "text": "查询最近内存超过七十五的设备列表",
        "template_id": "device.memory.over.list",
    },
    {
        "text": "查询最近cpu大于八十八且内存大于六十六的设备列表",
        "template_id": "device.cpu.memory.over.list",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark template-level LLM slot fallback.")
    parser.add_argument("--config", default="configs/templates.json")
    parser.add_argument("--base-url", default=os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("DASHSCOPE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_engines(
    *,
    config_path: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float,
) -> tuple[TemplateCapabilityEngine, TemplateCapabilityEngine]:
    baseline_config = load_template_config(config_path)
    llm_config = load_template_config(config_path)
    llm_config.settings.llm_slot_fallback_enabled = True
    resolver = OpenAICompatibleTemplateSlotResolver(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout,
    )
    return (
        TemplateCapabilityEngine(baseline_config),
        TemplateCapabilityEngine(llm_config, llm_template_slot_resolver=resolver),
    )


def run_case(engine: TemplateCapabilityEngine, text: str) -> tuple[dict[str, object], float]:
    start = time.perf_counter()
    payload = engine.match(text).to_dict()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return payload, elapsed_ms


def main() -> None:
    args = parse_args()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise SystemExit("Missing DASHSCOPE_API_KEY in environment.")

    baseline_engine, llm_engine = build_engines(
        config_path=args.config,
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        timeout=args.timeout,
    )
    rows: list[dict[str, object]] = []
    baseline_matched = 0
    llm_matched = 0
    llm_improved = 0
    llm_elapsed_values: list[float] = []
    wall_elapsed_values: list[float] = []

    for case in DEFAULT_CASES:
        baseline_payload, baseline_wall_ms = run_case(baseline_engine, case["text"])
        llm_payload, llm_wall_ms = run_case(llm_engine, case["text"])
        trace = llm_payload.get("trace", {})
        selected = trace.get("selected_template", {})
        selected_trace = selected.get("trace", {}) if isinstance(selected, dict) else {}
        slot_trace = selected_trace.get("slot_fallback_trace", {}) if isinstance(selected_trace, dict) else {}
        llm_elapsed_ms = float(slot_trace.get("elapsed_ms", 0.0) or 0.0)

        baseline_ok = (
            baseline_payload["template_id"] == case["template_id"]
            and baseline_payload["status"] == "matched"
        )
        llm_ok = (
            llm_payload["template_id"] == case["template_id"]
            and llm_payload["status"] == "matched"
        )
        baseline_matched += int(baseline_ok)
        llm_matched += int(llm_ok)
        if llm_ok and not baseline_ok:
            llm_improved += 1
        if llm_elapsed_ms > 0:
            llm_elapsed_values.append(llm_elapsed_ms)
        wall_elapsed_values.append(llm_wall_ms)
        rows.append(
            {
                "text": case["text"],
                "expected_template_id": case["template_id"],
                "baseline": {
                    "template_id": baseline_payload["template_id"],
                    "status": baseline_payload["status"],
                    "missing_slots": baseline_payload.get("missing_slots", []),
                    "wall_ms": round(baseline_wall_ms, 2),
                },
                "with_llm": {
                    "template_id": llm_payload["template_id"],
                    "status": llm_payload["status"],
                    "missing_slots": llm_payload.get("missing_slots", []),
                    "wall_ms": round(llm_wall_ms, 2),
                    "llm_elapsed_ms": round(llm_elapsed_ms, 2),
                },
            }
        )

    summary = {
        "case_count": len(DEFAULT_CASES),
        "baseline_matched": baseline_matched,
        "with_llm_matched": llm_matched,
        "llm_improved_cases": llm_improved,
        "avg_wall_ms": round(sum(wall_elapsed_values) / max(1, len(wall_elapsed_values)), 2),
        "avg_llm_elapsed_ms": round(sum(llm_elapsed_values) / max(1, len(llm_elapsed_values)), 2),
        "max_llm_elapsed_ms": round(max(llm_elapsed_values) if llm_elapsed_values else 0.0, 2),
        "within_3s_count": sum(1 for value in llm_elapsed_values if value <= 3000.0),
    }
    report = {"summary": summary, "cases": rows}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("Summary")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print("")
    print("Cases")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
