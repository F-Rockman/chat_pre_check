from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from chat_pre_check.infrastructure.config.loader import load_app_config
from chat_pre_check.infrastructure.seed_cases import (
    import_seed_cases,
    load_seed_case_rows,
    merge_seed_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import seed cases from CSV/JSON/JSONL into configs/capabilities.json"
    )
    parser.add_argument("--input", required=True, help="Input file path (.csv/.json/.jsonl)")
    parser.add_argument("--input-format", default="auto", choices=["auto", "csv", "json", "jsonl"])
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--output", default="configs/capabilities.json")
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
        help="Allow scene_id not found in capabilities definition",
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

    capabilities_payload = _load_capabilities_payload(output_path)
    existing = list(config.seed_cases)

    merged = merge_seed_cases(existing, imported, mode=args.merge_mode)
    _apply_seed_cases_to_capabilities(capabilities_payload, merged)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(capabilities_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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


def _load_capabilities_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": "v1", "capabilities": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload.setdefault("capabilities", [])
        return payload
    raise ValueError("capabilities file must be object")


def _apply_seed_cases_to_capabilities(
    payload: dict[str, Any],
    seed_cases: list[dict[str, Any]],
) -> None:
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise ValueError("capabilities.capabilities must be list")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in seed_cases:
        scene_id = str(item.get("scene_id", "")).strip()
        if not scene_id:
            continue
        grouped.setdefault(scene_id, []).append(dict(item))

    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        capability_id = str(capability.get("capability_id", "")).strip()
        cases = grouped.get(capability_id, [])
        normalized: list[dict[str, Any]] = []
        for case in cases:
            normalized.append(
                {
                    "case_id": case.get("case_id"),
                    "label": case.get("label"),
                    "text": case.get("text"),
                    "route_type": case.get("route_type", "route_nl2sql"),
                    "tags": case.get("tags", []),
                    "priority": case.get("priority", 100),
                    "owner": case.get("owner", ""),
                    "risk_level": case.get("risk_level", "medium"),
                    "enabled": case.get("enabled", True),
                }
            )
        capability["seed_cases"] = normalized


if __name__ == "__main__":
    main()
