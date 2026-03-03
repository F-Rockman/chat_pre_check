from __future__ import annotations

from collections import defaultdict

import pytest

from chat_pre_check.benchmark import evaluator
from chat_pre_check.benchmark.evaluator import BenchmarkCase


class _FakeDecision:
    def __init__(self, payload: dict) -> None:
        self.payload = dict(payload)

    def to_dict(self) -> dict:
        return dict(self.payload)


class _FakeEngine:
    def __init__(self, plans: dict[str, list[dict]]) -> None:
        self.plans = plans
        self.calls: defaultdict[str, int] = defaultdict(int)

    def route(self, request):
        seq = self.plans[request.input_text]
        idx = self.calls[request.input_text]
        self.calls[request.input_text] += 1
        payload = seq[idx] if idx < len(seq) else seq[-1]
        return _FakeDecision(payload)


def test_case_match_accepts_missing_slots_subset() -> None:
    ok, reason = evaluator._case_match(
        {"type": "clarify", "missing_slots": ["device_id"]},
        {"type": "clarify", "missing_slots": ["device_id", "time_range"]},
    )
    assert ok is True
    assert reason == "ok"


def test_signature_is_order_insensitive_for_missing_slots() -> None:
    left = evaluator._signature({"type": "clarify", "missing_slots": ["b", "a"]})
    right = evaluator._signature({"type": "clarify", "missing_slots": ["a", "b"]})
    assert left == right


def test_evaluate_benchmark_reports_weight_and_stability(monkeypatch) -> None:
    plans = {
        "稳定命中": [
            {"type": "route_template", "missing_slots": []},
            {"type": "route_template", "missing_slots": []},
            {"type": "route_template", "missing_slots": []},
        ],
        "不稳定失败": [
            {"type": "refuse", "missing_slots": []},
            {"type": "route_nl2sql", "missing_slots": []},
            {"type": "refuse", "missing_slots": []},
        ],
    }
    engine = _FakeEngine(plans)
    monkeypatch.setattr(evaluator, "build_benchmark_engine", lambda *args, **kwargs: engine)

    cases = [
        BenchmarkCase(
            case_id="c1",
            text="稳定命中",
            expected={"type": "route_template"},
            tags=["smoke"],
            weight=2.0,
        ),
        BenchmarkCase(
            case_id="c2",
            text="不稳定失败",
            expected={"type": "route_nl2sql"},
            tags=["smoke"],
            weight=1.0,
        ),
    ]

    summary = evaluator.evaluate_benchmark(cases, profile="mock", repeat=3)
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.exact_accuracy == pytest.approx(0.5)
    assert summary.weighted_accuracy == pytest.approx(2.0 / 3.0)
    assert summary.stability == pytest.approx(0.5)
    assert summary.per_type_accuracy["route_template"] == pytest.approx(1.0)
    assert summary.per_type_accuracy["route_nl2sql"] == pytest.approx(0.0)
    assert len(summary.failures) == 1
    assert summary.failures[0].case_id == "c2"

