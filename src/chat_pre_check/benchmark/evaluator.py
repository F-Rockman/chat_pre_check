from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.demo.fakes import DemoDeviceResolver, DemoRegionResolver, DemoVectorRetriever
from chat_pre_check.demo.local_runtime import build_local_fallback_engine
from chat_pre_check.domain.models import RouteRequest


@dataclass(slots=True)
class BenchmarkCase:
    case_id: str
    text: str
    expected: dict[str, Any]
    tags: list[str]
    weight: float = 1.0
    role: str | None = None
    tenant_id: str | None = None
    context: dict[str, Any] | None = None


@dataclass(slots=True)
class BenchmarkFailure:
    case_id: str
    text: str
    expected: dict[str, Any]
    actual: dict[str, Any]
    reason: str


@dataclass(slots=True)
class BenchmarkSummary:
    total: int
    passed: int
    failed: int
    weighted_accuracy: float
    exact_accuracy: float
    stability: float
    per_type_accuracy: dict[str, float]
    failures: list[BenchmarkFailure]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "weighted_accuracy": self.weighted_accuracy,
            "exact_accuracy": self.exact_accuracy,
            "stability": self.stability,
            "per_type_accuracy": self.per_type_accuracy,
            "failures": [
                {
                    "case_id": item.case_id,
                    "text": item.text,
                    "expected": item.expected,
                    "actual": item.actual,
                    "reason": item.reason,
                }
                for item in self.failures
            ],
        }


def load_benchmark_cases(dataset_path: str | Path) -> list[BenchmarkCase]:
    path = Path(dataset_path)
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("benchmark dataset must be a JSON list")
    cases: list[BenchmarkCase] = []
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"row {idx} must be object")
        case_id = str(row.get("id", "")).strip()
        text = str(row.get("text", ""))
        expected = row.get("expected")
        if not case_id or len(text) == 0 or not isinstance(expected, dict):
            raise ValueError(f"row {idx} missing required fields id/text/expected")
        tags = row.get("tags", [])
        if not isinstance(tags, list):
            raise ValueError(f"row {idx} tags must be list")
        weight = float(row.get("weight", 1.0))
        role_raw = row.get("role")
        role = str(role_raw).strip() if role_raw is not None else None
        if role == "":
            role = None
        tenant_raw = row.get("tenant_id")
        tenant_id = str(tenant_raw).strip() if tenant_raw is not None else None
        if tenant_id == "":
            tenant_id = None
        context = row.get("context")
        if context is not None and not isinstance(context, dict):
            raise ValueError(f"row {idx} context must be object")
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                text=text,
                expected=expected,
                tags=[str(tag) for tag in tags],
                weight=weight,
                role=role,
                tenant_id=tenant_id,
                context=dict(context) if isinstance(context, dict) else None,
            )
        )
    return cases


def build_benchmark_engine(
    profile: str,
    *,
    config_dir: str = "configs",
    os_url: str | None = None,
    search_backend: str | None = None,
):
    if profile == "local_fallback":
        return build_local_fallback_engine(config_dir=config_dir)
    if profile == "mock":
        return build_engine(
            config_dir=config_dir,
            retriever_override=DemoVectorRetriever(),
            device_resolver_override=DemoDeviceResolver(),
            region_resolver_override=DemoRegionResolver(),
        )
    if profile == "live":
        return build_engine(
            config_dir=config_dir,
            os_url=os_url,
            search_backend=search_backend,
        )
    raise ValueError(f"Unsupported profile: {profile}")


def evaluate_benchmark(
    cases: list[BenchmarkCase],
    *,
    profile: str = "local_fallback",
    config_dir: str = "configs",
    os_url: str | None = None,
    search_backend: str | None = None,
    trace_level: str = "compact",
    repeat: int = 3,
) -> BenchmarkSummary:
    engine = build_benchmark_engine(
        profile,
        config_dir=config_dir,
        os_url=os_url,
        search_backend=search_backend,
    )

    failures: list[BenchmarkFailure] = []
    per_type_total = Counter()
    per_type_pass = Counter()
    weighted_total = 0.0
    weighted_pass = 0.0
    stable_count = 0

    for case in cases:
        actual_runs: list[dict[str, Any]] = []
        for _ in range(max(1, repeat)):
            decision = engine.route(
                RouteRequest(
                    input_text=case.text,
                    context=dict(case.context) if isinstance(case.context, dict) else {},
                    tenant_id=case.tenant_id,
                    role=case.role,
                    trace_level=trace_level,
                )
            )
            actual_runs.append(decision.to_dict())

        first = actual_runs[0]
        expected_type = str(case.expected.get("type", ""))
        if expected_type:
            per_type_total[expected_type] += 1

        ok, reason = _case_match(case.expected, first)
        weighted_total += case.weight
        if ok:
            weighted_pass += case.weight
            if expected_type:
                per_type_pass[expected_type] += 1
        else:
            failures.append(
                BenchmarkFailure(
                    case_id=case.case_id,
                    text=case.text,
                    expected=case.expected,
                    actual=_compact_actual(first),
                    reason=reason,
                )
            )

        if _is_stable(actual_runs):
            stable_count += 1

    total = len(cases)
    passed = total - len(failures)
    per_type_accuracy = {}
    for expected_type, count in per_type_total.items():
        per_type_accuracy[expected_type] = per_type_pass[expected_type] / max(1, count)

    return BenchmarkSummary(
        total=total,
        passed=passed,
        failed=len(failures),
        weighted_accuracy=(weighted_pass / max(1e-9, weighted_total)),
        exact_accuracy=(passed / max(1, total)),
        stability=(stable_count / max(1, total)),
        per_type_accuracy=per_type_accuracy,
        failures=failures,
    )


def _case_match(expected: dict[str, Any], actual: dict[str, Any]) -> tuple[bool, str]:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key == "missing_slots":
            if not isinstance(expected_value, list):
                return False, "invalid_expected_missing_slots"
            actual_missing = set(actual_value or [])
            expected_missing = set(expected_value)
            if not expected_missing.issubset(actual_missing):
                return False, f"missing_slots_mismatch expected_subset={sorted(expected_missing)} actual={sorted(actual_missing)}"
            continue
        if actual_value != expected_value:
            return False, f"field_mismatch:{key}:expected={expected_value}:actual={actual_value}"
    return True, "ok"


def _compact_actual(actual: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": actual.get("type"),
        "scene": actual.get("scene"),
        "template_id": actual.get("template_id"),
        "out_of_scope_reason": actual.get("out_of_scope_reason"),
        "missing_slots": actual.get("missing_slots", []),
    }


def _is_stable(actual_runs: list[dict[str, Any]]) -> bool:
    signatures = {_signature(item) for item in actual_runs}
    return len(signatures) == 1


def _signature(actual: dict[str, Any]) -> str:
    payload = {
        "type": actual.get("type"),
        "scene": actual.get("scene"),
        "template_id": actual.get("template_id"),
        "out_of_scope_reason": actual.get("out_of_scope_reason"),
        "missing_slots": sorted(actual.get("missing_slots", [])),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
