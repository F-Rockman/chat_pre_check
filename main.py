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
from template_capability.fallback import (
    OpenAICompatibleFallbackResolver,
    OpenAICompatibleTemplateIntentVerifier,
    OpenAICompatibleTemplateSlotResolver,
)

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
        "text": "过去24小时接口错包告警前10名",
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
    # 模板选择级 fallback 只在边界 case 上裁决候选，不做全模板推理。
    parser.add_argument("--llm-fallback", action="store_true")
    parser.add_argument("--llm-base-url", default=os.environ.get("DASHSCOPE_BASE_URL", "https://coding.dashscope.aliyuncs.com/v1"))
    parser.add_argument("--llm-model", default=os.environ.get("DASHSCOPE_MODEL", "qwen3-coder-plus"))
    parser.add_argument("--llm-timeout", type=float, default=5.0)
    # top1 模板稳定命中后，用 LLM 做“问法意图是否一致”的二元裁决。
    parser.add_argument("--llm-intent-check", action="store_true")
    parser.add_argument("--llm-intent-base-url", default=os.environ.get("DASHSCOPE_BASE_URL", "https://coding.dashscope.aliyuncs.com/v1"))
    parser.add_argument("--llm-intent-model", default=os.environ.get("DASHSCOPE_MODEL", "qwen3-coder-plus"))
    parser.add_argument("--llm-intent-timeout", type=float, default=5.0)
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
    fallback_resolver = None
    intent_verifier = None
    slot_resolver = None
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if args.llm_fallback or args.llm_intent_check or args.llm_slot_fallback:
        if not api_key:
            raise SystemExit("Missing DASHSCOPE_API_KEY in environment.")
    if args.llm_fallback:
        config.settings.llm_fallback_enabled = True
        fallback_resolver = OpenAICompatibleFallbackResolver(
            api_key=api_key or "",
            base_url=args.llm_base_url,
            model=args.llm_model,
            timeout_seconds=args.llm_timeout,
        )
    if args.llm_intent_check:
        config.settings.llm_intent_check_enabled = True
        intent_verifier = OpenAICompatibleTemplateIntentVerifier(
            api_key=api_key or "",
            base_url=args.llm_intent_base_url,
            model=args.llm_intent_model,
            timeout_seconds=args.llm_intent_timeout,
        )
    if args.llm_slot_fallback:
        # 一旦显式打开 CLI 开关，就同步打开配置里的模板级补参总开关。
        config.settings.llm_slot_fallback_enabled = True
        slot_resolver = OpenAICompatibleTemplateSlotResolver(
            api_key=api_key or "",
            base_url=args.llm_slot_base_url,
            model=args.llm_slot_model,
            timeout_seconds=args.llm_slot_timeout,
        )
    engine = TemplateCapabilityEngine(
        config,
        llm_fallback_resolver=fallback_resolver,
        llm_template_intent_verifier=intent_verifier,
        llm_template_slot_resolver=slot_resolver,
    )
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
