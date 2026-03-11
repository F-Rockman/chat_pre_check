from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from template_capability.evaluation import (
    build_engine_and_evaluate,
    render_report_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate metric-query templates against a static corpus.")
    parser.add_argument("--config", default="configs/templates.json")
    parser.add_argument("--corpus", default="tests/fixtures/evaluation_cases.json")
    parser.add_argument("--output", default="")
    parser.add_argument("--json", action="store_true", help="Print JSON report instead of text.")
    parser.add_argument("--fail-on-errors", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_engine_and_evaluate(
        config_path=args.config,
        corpus_path=args.corpus,
    )
    payload = report.to_dict()
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_report_text(report))
    if args.fail_on_errors and report.failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
