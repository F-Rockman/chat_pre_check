from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 允许直接从仓库根目录运行 `python main.py`，不要求先安装包。
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from template_capability.config import load_template_config
from template_capability.engine import TemplateCapabilityEngine
from template_capability.fallback import OpenAICompatibleTemplateSlotResolver

# 这组样例承担两个职责：
# 1. 给开发者一个开箱即跑的 CLI 演示入口
# 2. 覆盖 matched / partial / unmatched 的典型问数场景
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
    """定义 CLI 入口参数。"""
    parser = argparse.ArgumentParser(description="Generic metric-query template matcher")
    parser.add_argument("--config", default="configs/templates.json")
    parser.add_argument("--input", default="", help="Run a single input text")
    parser.add_argument("--interactive", action="store_true")
    # 这里的 LLM 只用于“模板已命中后的定向补参”，不是全量模板推理。
    parser.add_argument("--llm-slot-fallback", action="store_true")
    parser.add_argument("--llm-slot-base-url", default=os.environ.get("DASHSCOPE_BASE_URL", "https://coding.dashscope.aliyuncs.com/v1"))
    parser.add_argument("--llm-slot-model", default=os.environ.get("DASHSCOPE_MODEL", "qwen3-coder-plus"))
    parser.add_argument("--llm-slot-timeout", type=float, default=5.0)
    return parser.parse_args()


def run_one(engine: TemplateCapabilityEngine, text: str) -> None:
    """执行单条 query，并把完整结果打印成 JSON。"""
    payload = engine.match(text).to_dict()
    print("=" * 80)
    print(f"INPUT      : {text}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_interactive(engine: TemplateCapabilityEngine) -> None:
    """简单 REPL，方便本地人工试问法。"""
    print("Interactive mode. 输入 exit 退出。")
    while True:
        text = input(">>> ").strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            break
        run_one(engine, text)


def main() -> None:
    """CLI 主入口。

    优先级顺序是：
    1. `--interactive`: 进入交互模式
    2. `--input`: 跑单条输入
    3. 默认：把内置样例跑一遍，方便快速观察结果
    """
    args = parse_args()
    config = load_template_config(args.config)
    resolver = None
    if args.llm_slot_fallback:
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise SystemExit("Missing DASHSCOPE_API_KEY in environment.")
        # 一旦显式打开 CLI 开关，就同步打开配置里的模板级补参总开关。
        config.settings.llm_slot_fallback_enabled = True
        resolver = OpenAICompatibleTemplateSlotResolver(
            api_key=api_key,
            base_url=args.llm_slot_base_url,
            model=args.llm_slot_model,
            timeout_seconds=args.llm_slot_timeout,
        )
    engine = TemplateCapabilityEngine(config, llm_template_slot_resolver=resolver)
    if args.interactive:
        run_interactive(engine)
        return
    if args.input:
        run_one(engine, args.input)
        return
    # 未传参数时，默认跑内置样例，便于快速观察模板能力边界。
    for item in DEFAULT_EXAMPLES:
        run_one(engine, item["text"])


if __name__ == "__main__":
    main()
