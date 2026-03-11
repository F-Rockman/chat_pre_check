from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 和 main.py 一样，允许直接从仓库根目录运行脚本而不先安装包。
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from template_capability.evaluation import (
    build_engine_and_evaluate,
    render_report_text,
)


def parse_args() -> argparse.Namespace:
    """定义评测脚本参数。"""
    parser = argparse.ArgumentParser(description="Evaluate metric-query templates against a static corpus.")
    parser.add_argument("--config", default="configs/templates.json")
    parser.add_argument("--corpus", default="tests/fixtures/evaluation_cases.json")
    # output 始终写 JSON，方便后续被报告系统或 CI 消费。
    parser.add_argument("--output", default="")
    parser.add_argument("--json", action="store_true", help="Print JSON report instead of text.")
    # 适合接 CI，存在失败样本时直接返回非 0。
    parser.add_argument("--fail-on-errors", action="store_true")
    return parser.parse_args()


def main() -> None:
    """评测脚本主入口。"""
    args = parse_args()
    report = build_engine_and_evaluate(
        config_path=args.config,
        corpus_path=args.corpus,
    )
    payload = report.to_dict()
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 落盘时统一写结构化 JSON；终端展示格式由 --json 控制。
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        # 默认文本报告更适合人工快速浏览。
        print(render_report_text(report))
    if args.fail_on_errors and report.failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
