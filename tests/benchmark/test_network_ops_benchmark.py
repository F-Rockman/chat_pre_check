from __future__ import annotations

from chat_pre_check.benchmark.evaluator import evaluate_benchmark, load_benchmark_cases


BUSINESS_DATASET = "benchmark/network_ops_business_golden_v1.json"
REGRESSION_DATASET = "benchmark/network_ops_regression_local_fallback_v1.json"


def test_benchmark_dataset_schema_and_size():
    business = load_benchmark_cases(BUSINESS_DATASET)
    regression = load_benchmark_cases(REGRESSION_DATASET)
    assert len(business) >= 40
    assert len(regression) >= 40


def test_business_golden_accuracy_and_stability_local_fallback():
    cases = load_benchmark_cases(BUSINESS_DATASET)
    summary = evaluate_benchmark(cases, profile="local_fallback", repeat=3)
    assert summary.exact_accuracy >= 0.55
    assert summary.stability == 1.0


def test_local_regression_dataset_is_fully_stable():
    cases = load_benchmark_cases(REGRESSION_DATASET)
    summary = evaluate_benchmark(cases, profile="local_fallback", repeat=3)
    assert summary.exact_accuracy == 1.0
    assert summary.weighted_accuracy == 1.0
    assert summary.stability == 1.0
