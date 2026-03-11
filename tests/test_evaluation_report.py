from __future__ import annotations

import json
from pathlib import Path

from template_capability.evaluation import (
    EvaluationCase,
    evaluate_engine,
    load_evaluation_cases,
    render_report_text,
)
from template_capability.engine import TemplateCapabilityEngine


def build_engine() -> TemplateCapabilityEngine:
    return TemplateCapabilityEngine.from_file("configs/templates.json")


def test_evaluation_report_passes_current_corpus():
    engine = build_engine()
    cases = load_evaluation_cases("tests/fixtures/evaluation_cases.json")
    report = evaluate_engine(engine, cases)
    fixture = json.loads(Path("tests/fixtures/evaluation_cases.json").read_text(encoding="utf-8"))

    expected_total = sum(len(fixture[bucket]) for bucket in fixture)
    assert report.total_cases == expected_total
    assert report.passed == expected_total
    assert report.failed == 0
    assert report.buckets["matched"].total == len(fixture["matched"])
    assert report.buckets["partial"].total == len(fixture["partial"])
    assert report.buckets["unmatched"].total == len(fixture["unmatched"])
    assert report.buckets["not_full_match"].total == len(fixture["not_full_match"])
    assert report.templates_without_cases == []
    assert "Summary" in render_report_text(report)


def test_evaluation_report_exposes_failures_and_uncovered_templates():
    engine = build_engine()
    cases = [
        EvaluationCase(
            bucket="matched",
            text="近24小时接口错误包告警Top10",
            expected_template_id="alarm.interface.error.topn",
        ),
        EvaluationCase(
            bucket="matched",
            text="近24小时接口错误包告警Top10",
            expected_template_id="device.offline.count",
        ),
    ]

    report = evaluate_engine(engine, cases)

    assert report.total_cases == 2
    assert report.passed == 1
    assert report.failed == 1
    assert len(report.failures) == 1
    assert report.failures[0].expected_template_id == "device.offline.count"
    assert "network.packet_loss.rank.topn" in report.templates_without_cases
    assert "alarm.critical.count" in report.templates_without_cases
    assert "device.cpu.over.list" in report.templates_without_cases
