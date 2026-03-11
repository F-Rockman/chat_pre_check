from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from template_capability.engine import TemplateCapabilityEngine

DEFAULT_EXAMPLES = [
    {
        "text": "近24小时接口错误包告警Top10",
        "expected_template_id": "alarm.interface.error.topn",
        "expected_status": "matched",
    },
    {
        "text": "昨天华东离线设备数",
        "expected_template_id": "device.offline.count",
        "expected_status": "matched",
    },
    {
        "text": "查询最近cpu大于80的设备列表",
        "expected_template_id": "device.cpu.over.list",
        "expected_status": "matched",
    },
    {
        "text": "查询cup大余88的设别列表",
        "expected_template_id": "device.cpu.over.list",
        "expected_status": "matched",
    },
    {
        "text": "列出华东cpu超过85的设备",
        "expected_template_id": "device.cpu.over.list",
        "expected_status": "matched",
    },
    {
        "text": "查询最近cpu大于80且内存大于70的设备列表",
        "expected_template_id": "device.cpu.memory.over.list",
        "expected_status": "matched",
    },
    {
        "text": "最近7天上海cpu利用率超过80且内存使用率超过70的设备有哪些",
        "expected_template_id": "device.cpu.memory.over.list",
        "expected_status": "matched",
    },
    {
        "text": "查询近24小时cpu大于80 内存大于70 磁盘大于85的设备列表",
        "expected_template_id": "device.cpu.memory.disk.over.list",
        "expected_status": "matched",
    },
    {
        "text": "最近cpu高于90 内存高于80 磁盘高于85的设备有哪些",
        "expected_template_id": "device.cpu.memory.disk.over.list",
        "expected_status": "matched",
    },
    {
        "text": "查询最近内存大于75的设备列表",
        "expected_template_id": "device.memory.over.list",
        "expected_status": "matched",
    },
    {
        "text": "列出华南内存超过70的设备",
        "expected_template_id": "device.memory.over.list",
        "expected_status": "matched",
    },
    {
        "text": "查询最近cpu大于80的设备",
        "expected_template_id": "device.cpu.over.list",
        "expected_status": "partial",
    },
    {
        "text": "查询最近cpu大于80且内存大于70的设备",
        "expected_template_id": "device.cpu.memory.over.list",
        "expected_status": "partial",
    },
    {
        "text": "查询最近内存大于75的设备",
        "expected_template_id": "device.memory.over.list",
        "expected_status": "partial",
    },
    {
        "text": "查询近24小时cpu大于80 内存大于70 磁盘大于85的设备",
        "expected_template_id": "device.cpu.memory.disk.over.list",
        "expected_status": "partial",
    },
    {
        "text": "为什么接口错误包告警这么多",
        "expected_template_id": -1,
        "expected_status": "unmatched",
    },
    {
        "text": "帮我写一段年终总结",
        "expected_template_id": -1,
        "expected_status": "unmatched",
    },
    {
        "text": "给我cpu大于80设备的分析结论",
        "expected_template_id": -1,
        "expected_status": "unmatched",
    },
    {
        "text": "请输出cpu和内存异常设备的优化建议",
        "expected_template_id": -1,
        "expected_status": "unmatched",
    },
]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic metric-query template matcher")
    parser.add_argument("--config", default="configs/templates.json")
    parser.add_argument("--input", default="", help="Run a single input text")
    parser.add_argument("--interactive", action="store_true")
    return parser.parse_args()

def run_one(engine: TemplateCapabilityEngine, text: str) -> None:
    payload = engine.match(text).to_dict()
    print("=" * 80)
    print(f"INPUT      : {text}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

def run_interactive(engine: TemplateCapabilityEngine) -> None:
    print("Interactive mode. 输入 exit 退出。")
    while True:
        text = input(">>> ").strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            break
        run_one(engine, text)

def main() -> None:
    args = parse_args()
    engine = TemplateCapabilityEngine.from_file(args.config)
    if args.interactive:
        run_interactive(engine)
        return
    if args.input:
        run_one(engine, args.input)
        return
    for item in DEFAULT_EXAMPLES:
        run_one(engine, item["text"])


if __name__ == "__main__":
    main()
