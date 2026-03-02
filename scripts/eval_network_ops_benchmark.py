from __future__ import annotations

import argparse
import json
from pathlib import Path

from chat_pre_check.benchmark.evaluator import evaluate_benchmark, load_benchmark_cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate routing accuracy and stability on network ops benchmark."
    )
    parser.add_argument(
        "--dataset",
        default="benchmark/network_ops_business_golden_v1.json",
        help="Benchmark dataset path (JSON list).",
    )
    parser.add_argument(
        "--profile",
        choices=["local_fallback", "mock", "live"],
        default="local_fallback",
    )
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--os-url", default=None)
    parser.add_argument(
        "--search-backend",
        choices=["opensearch", "elasticsearch", "es"],
        default=None,
        help="Search backend type (effective when --profile live).",
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--trace-level", choices=["compact", "debug"], default="compact")
    parser.add_argument("--min-accuracy", type=float, default=0.55)
    parser.add_argument("--min-stability", type=float, default=1.0)
    parser.add_argument("--report-file", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_benchmark_cases(args.dataset)
    summary = evaluate_benchmark(
        cases,
        profile=args.profile,
        config_dir=args.config_dir,
        os_url=args.os_url,
        search_backend=args.search_backend,
        trace_level=args.trace_level,
        repeat=args.repeat,
    )
    payload = summary.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.report_file:
        Path(args.report_file).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if summary.exact_accuracy < args.min_accuracy:
        raise SystemExit(
            f"accuracy_gate_failed: exact_accuracy={summary.exact_accuracy:.4f} "
            f"< min_accuracy={args.min_accuracy:.4f}"
        )
    if summary.stability < args.min_stability:
        raise SystemExit(
            f"stability_gate_failed: stability={summary.stability:.4f} "
            f"< min_stability={args.min_stability:.4f}"
        )


if __name__ == "__main__":
    main()
