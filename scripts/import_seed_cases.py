from __future__ import annotations

import argparse
import json
from pathlib import Path

from chat_pre_check.infrastructure.config.loader import load_app_config
from chat_pre_check.infrastructure.seed_cases import (
    dump_seed_cases,
    import_seed_cases,
    load_seed_case_rows,
    merge_seed_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import seed cases from CSV/JSON/JSONL into configs/seed_cases.json"
    )
    parser.add_argument("--input", required=True, help="Input file path (.csv/.json/.jsonl)")
    parser.add_argument("--input-format", default="auto", choices=["auto", "csv", "json", "jsonl"])
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--output", default="configs/seed_cases.json")
    parser.add_argument("--merge-mode", default="replace", choices=["replace", "upsert"])
    parser.add_argument(
        "--on-duplicate",
        default="error",
        choices=["error", "keep_first", "keep_last"],
    )
    parser.add_argument("--strict", action="store_true", help="Fail fast on first invalid row")
    parser.add_argument(
        "--allow-unknown-scene",
        action="store_true",
        help="Allow scene_id not found in scenes.json",
    )
    parser.add_argument(
        "--error-report",
        default="",
        help="Optional path to save invalid rows detail as JSON",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    config = load_app_config(args.config_dir)
    known_scene_ids = {scene["scene_id"] for scene in config.scenes}

    rows = load_seed_case_rows(input_path, input_format=args.input_format)
    imported, result = import_seed_cases(
        rows,
        known_scene_ids=known_scene_ids,
        strict=args.strict,
        allow_unknown_scene=args.allow_unknown_scene,
        on_duplicate=args.on_duplicate,
    )

    existing = []
    if output_path.exists():
        existing_data = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(existing_data, list):
            existing = existing_data

    merged = merge_seed_cases(existing, imported, mode=args.merge_mode)
    dump_seed_cases(output_path, merged)

    if args.error_report:
        Path(args.error_report).write_text(
            json.dumps(result.errors, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(
        "seed_case_import_done "
        f"rows_total={result.rows_total} rows_ok={result.rows_ok} "
        f"rows_invalid={result.rows_invalid} duplicates={result.duplicates} "
        f"output_count={len(merged)} output={output_path}"
    )
    if result.errors and not args.strict:
        print(f"invalid_rows_saved={args.error_report or 'N/A'}")


if __name__ == "__main__":
    main()
