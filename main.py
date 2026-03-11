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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone template capability runner")
    parser.add_argument("--config", default="configs/templates.json")
    parser.add_argument("--input", default="", help="Run a single input text")
    parser.add_argument("--interactive", action="store_true")
    return parser.parse_args()


def run_one(engine: TemplateCapabilityEngine, text: str) -> None:
    payload = engine.route(text).to_dict()
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
    for text in [
        "近24小时接口错误包告警Top10",
        "近24小时接口错误包告警",
        "昨天华东离线设备数",
        "帮我写一段年终总结",
    ]:
        run_one(engine, text)


if __name__ == "__main__":
    main()

