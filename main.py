from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.demo.runtime import (
    build_mock_demo_engine,
    print_route_summary,
    route_payload,
)


DEMO_SETS = {
    "basic": [
        "帮我写一段年终总结",
        "查告警",
        "查近24小时核心网告警Top10",
        "统计近7天每个地市告警与工单关联率",
    ],
    "network_ops": [
        "近24小时接口错误包告警Top10",
        "近7天华东BGP flap Top20",
        "近24小时设备CPU利用率Top10",
        "近30天华北骨干网抖动与丢包相关性",
        "昨天离线设备数",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quick local demo runner for chat_pre_check",
    )
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--trace-level", choices=["compact", "debug"], default="compact")
    parser.add_argument("--role", default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--os-url", default=None, help="OpenSearch URL for live mode")
    parser.add_argument("--demo-set", choices=["basic", "network_ops", "all"], default="basic")
    parser.add_argument("--input", default="", help="Run a single input text")
    parser.add_argument("--interactive", action="store_true", help="Interactive REPL mode")
    parser.add_argument("--show-trace", action="store_true")
    return parser.parse_args()


def build_demo_engine(args: argparse.Namespace):
    if args.mode == "live":
        return build_engine(
            config_dir=args.config_dir,
            os_url=args.os_url or os.getenv("CHAT_PRE_CHECK_OS_URL"),
        )

    return build_mock_demo_engine(config_dir=args.config_dir)


def run_one(engine, text: str, args: argparse.Namespace) -> None:
    payload = route_payload(
        engine,
        text,
        role=args.role,
        tenant_id=args.tenant_id,
        trace_level=args.trace_level,
    )
    print_route_summary(text, payload, show_trace=args.show_trace)


def run_demo_set(engine, args: argparse.Namespace) -> None:
    if args.input:
        run_one(engine, args.input, args)
        return

    if args.demo_set == "all":
        texts = DEMO_SETS["basic"] + DEMO_SETS["network_ops"]
    else:
        texts = DEMO_SETS[args.demo_set]
    for text in texts:
        run_one(engine, text, args)


def run_interactive(engine, args: argparse.Namespace) -> None:
    print("Interactive mode. 输入 exit 退出。")
    while True:
        text = input(">>> ").strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            break
        run_one(engine, text, args)


def main() -> None:
    args = parse_args()
    engine = build_demo_engine(args)
    if args.interactive:
        run_interactive(engine, args)
    else:
        run_demo_set(engine, args)


if __name__ == "__main__":
    main()
