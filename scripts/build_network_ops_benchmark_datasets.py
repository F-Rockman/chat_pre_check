from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chat_pre_check.demo.local_runtime import build_local_fallback_engine
from chat_pre_check.domain.models import RouteRequest
from tests.acceptance.test_network_ops_extended import EXTENDED_CASES
from tests.acceptance.test_routing_acceptance import CASES as BASE_CASES


OUT_DIR = Path("benchmark")
BUSINESS_FILE = OUT_DIR / "network_ops_business_golden_v1.json"
REGRESSION_FILE = OUT_DIR / "network_ops_regression_local_fallback_v1.json"


def _copy_optional_request_fields(source: dict, target: dict) -> None:
    for key in ("role", "tenant_id", "context"):
        if key not in source:
            continue
        value = source.get(key)
        if value is None:
            continue
        target[key] = value


def _expected_from_case(case: dict) -> dict:
    expected = {"type": case["expected_type"]}
    if "expected_scene" in case:
        expected["scene"] = case["expected_scene"]
    if "expected_template" in case:
        expected["template_id"] = case["expected_template"]
    if "expected_reason" in case:
        expected["out_of_scope_reason"] = case["expected_reason"]
    if "expected_missing" in case:
        expected["missing_slots"] = [case["expected_missing"]]
    return expected


def build_business_golden_dataset() -> list[dict]:
    rows: list[dict] = []
    for case in BASE_CASES + EXTENDED_CASES:
        row = {
            "id": f"biz::{case['id']}",
            "text": case["text"],
            "expected": _expected_from_case(case),
            "tags": ["network_ops", "business_golden", case["expected_type"]],
            "weight": 1.0,
        }
        if row["expected"]["type"] in ("route_template", "route_nl2sql"):
            row["weight"] = 1.2
        if row["expected"]["type"] == "refuse":
            row["weight"] = 1.1
        _copy_optional_request_fields(case, row)
        rows.append(row)
    return rows


def _expected_from_actual(actual: dict) -> dict:
    expected = {
        "type": actual.get("type"),
    }
    for key in ("scene", "template_id", "out_of_scope_reason"):
        value = actual.get(key)
        if value not in (None, ""):
            expected[key] = value
    missing_slots = actual.get("missing_slots", [])
    if missing_slots:
        expected["missing_slots"] = list(missing_slots)
    return expected


def build_regression_dataset_from_local(business_rows: list[dict]) -> list[dict]:
    engine = build_local_fallback_engine("configs")
    rows: list[dict] = []
    for item in business_rows:
        context = item.get("context")
        result = engine.route(
            RouteRequest(
                input_text=item["text"],
                context=dict(context) if isinstance(context, dict) else {},
                tenant_id=item.get("tenant_id"),
                role=item.get("role"),
                trace_level="compact",
            )
        )
        actual = result.to_dict()
        row = {
            "id": item["id"].replace("biz::", "reg::"),
            "text": item["text"],
            "expected": _expected_from_actual(actual),
            "tags": ["network_ops", "local_regression", actual.get("type", "unknown")],
            "weight": item.get("weight", 1.0),
        }
        _copy_optional_request_fields(item, row)
        rows.append(row)
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    business_rows = build_business_golden_dataset()
    regression_rows = build_regression_dataset_from_local(business_rows)
    BUSINESS_FILE.write_text(
        json.dumps(business_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    REGRESSION_FILE.write_text(
        json.dumps(regression_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "benchmark_datasets_built "
        f"business={BUSINESS_FILE} rows={len(business_rows)} "
        f"regression={REGRESSION_FILE} rows={len(regression_rows)}"
    )


if __name__ == "__main__":
    main()
