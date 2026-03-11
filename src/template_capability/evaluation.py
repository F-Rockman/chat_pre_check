from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from template_capability.engine import TemplateCapabilityEngine


MATCHED_BUCKET = "matched"
PARTIAL_BUCKET = "partial"
UNMATCHED_BUCKET = "unmatched"
NOT_FULL_MATCH_BUCKET = "not_full_match"
SUPPORTED_BUCKETS = (
    MATCHED_BUCKET,
    PARTIAL_BUCKET,
    UNMATCHED_BUCKET,
    NOT_FULL_MATCH_BUCKET,
)


@dataclass(slots=True)
class EvaluationCase:
    bucket: str
    text: str
    expected_template_id: str | int | None = None


@dataclass(slots=True)
class EvaluationFailure:
    bucket: str
    text: str
    expected_template_id: str | int | None
    actual_template_id: str | int
    expected_status: str
    actual_status: str
    score: float
    missing_slots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "text": self.text,
            "expected_template_id": self.expected_template_id,
            "actual_template_id": self.actual_template_id,
            "expected_status": self.expected_status,
            "actual_status": self.actual_status,
            "score": self.score,
            "missing_slots": self.missing_slots,
        }


@dataclass(slots=True)
class BucketStats:
    name: str
    total: int = 0
    passed: int = 0
    failed: int = 0

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
        }


@dataclass(slots=True)
class TemplateCoverage:
    template_id: str
    matched_cases: int = 0
    partial_cases: int = 0
    total_cases: int = 0
    failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "matched_cases": self.matched_cases,
            "partial_cases": self.partial_cases,
            "total_cases": self.total_cases,
            "failures": self.failures,
        }


@dataclass(slots=True)
class EvaluationReport:
    total_cases: int
    passed: int
    failed: int
    buckets: dict[str, BucketStats]
    failures: list[EvaluationFailure]
    template_coverage: dict[str, TemplateCoverage]
    templates_without_cases: list[str]

    @property
    def pass_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.passed / self.total_cases

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "total_cases": self.total_cases,
                "passed": self.passed,
                "failed": self.failed,
                "pass_rate": self.pass_rate,
            },
            "buckets": {
                name: stats.to_dict()
                for name, stats in self.buckets.items()
            },
            "template_coverage": {
                template_id: coverage.to_dict()
                for template_id, coverage in self.template_coverage.items()
            },
            "templates_without_cases": self.templates_without_cases,
            "failures": [failure.to_dict() for failure in self.failures],
        }


def load_evaluation_cases(path: str | Path) -> list[EvaluationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[EvaluationCase] = []
    for bucket in SUPPORTED_BUCKETS:
        for item in payload.get(bucket, []):
            if not isinstance(item, dict) or "text" not in item:
                continue
            cases.append(
                EvaluationCase(
                    bucket=bucket,
                    text=str(item["text"]),
                    expected_template_id=item.get("template_id"),
                )
            )
    return cases


def evaluate_engine(
    engine: TemplateCapabilityEngine,
    cases: list[EvaluationCase],
) -> EvaluationReport:
    buckets = {bucket: BucketStats(name=bucket) for bucket in SUPPORTED_BUCKETS}
    template_coverage = {
        template_id: TemplateCoverage(template_id=template_id)
        for template_id in engine.templates
    }
    failures: list[EvaluationFailure] = []
    passed = 0

    for case in cases:
        result = engine.match(case.text).to_dict()
        bucket_stats = buckets[case.bucket]
        bucket_stats.total += 1

        if case.expected_template_id in template_coverage:
            coverage = template_coverage[str(case.expected_template_id)]
            coverage.total_cases += 1
            if case.bucket == MATCHED_BUCKET:
                coverage.matched_cases += 1
            elif case.bucket == PARTIAL_BUCKET:
                coverage.partial_cases += 1

        success = _case_passed(case, result)
        if success:
            passed += 1
            bucket_stats.passed += 1
            continue

        bucket_stats.failed += 1
        actual_template_id = result["template_id"]
        if isinstance(actual_template_id, str) and actual_template_id in template_coverage:
            template_coverage[actual_template_id].failures += 1
        if case.expected_template_id in template_coverage:
            template_coverage[str(case.expected_template_id)].failures += 1
        failures.append(
            EvaluationFailure(
                bucket=case.bucket,
                text=case.text,
                expected_template_id=case.expected_template_id,
                actual_template_id=actual_template_id,
                expected_status=_expected_status(case.bucket),
                actual_status=str(result["status"]),
                score=float(result["score"]),
                missing_slots=[str(slot) for slot in result.get("missing_slots", [])],
            )
        )

    total_cases = len(cases)
    templates_without_cases = [
        template_id
        for template_id, coverage in template_coverage.items()
        if coverage.total_cases == 0
    ]
    return EvaluationReport(
        total_cases=total_cases,
        passed=passed,
        failed=total_cases - passed,
        buckets=buckets,
        failures=failures,
        template_coverage=template_coverage,
        templates_without_cases=templates_without_cases,
    )


def build_engine_and_evaluate(
    *,
    config_path: str | Path,
    corpus_path: str | Path,
) -> EvaluationReport:
    engine = TemplateCapabilityEngine.from_file(str(config_path))
    cases = load_evaluation_cases(corpus_path)
    return evaluate_engine(engine, cases)


def render_report_text(report: EvaluationReport) -> str:
    lines = [
        "Summary",
        f"total_cases: {report.total_cases}",
        f"passed: {report.passed}",
        f"failed: {report.failed}",
        f"pass_rate: {report.pass_rate:.2%}",
        "",
        "Buckets",
    ]
    for bucket in SUPPORTED_BUCKETS:
        stats = report.buckets[bucket]
        lines.append(
            f"{bucket}: total={stats.total} passed={stats.passed} failed={stats.failed} pass_rate={stats.pass_rate:.2%}"
        )
    lines.extend(["", "Template Coverage"])
    for template_id in sorted(report.template_coverage):
        coverage = report.template_coverage[template_id]
        lines.append(
            f"{template_id}: total={coverage.total_cases} matched={coverage.matched_cases} partial={coverage.partial_cases} failures={coverage.failures}"
        )
    if report.templates_without_cases:
        lines.extend(["", "Templates Without Cases"])
        lines.extend(sorted(report.templates_without_cases))
    if report.failures:
        lines.extend(["", "Failures"])
        for failure in report.failures[:20]:
            lines.append(
                f"{failure.bucket}: expected={failure.expected_template_id}/{failure.expected_status} actual={failure.actual_template_id}/{failure.actual_status} score={failure.score:.4f} text={failure.text}"
            )
        if len(report.failures) > 20:
            lines.append(f"... truncated {len(report.failures) - 20} more failures")
    return "\n".join(lines)


def _case_passed(case: EvaluationCase, result: dict[str, Any]) -> bool:
    status = str(result["status"])
    template_id = result["template_id"]
    if case.bucket == MATCHED_BUCKET:
        return status == "matched" and template_id == case.expected_template_id
    if case.bucket == PARTIAL_BUCKET:
        return status == "partial" and template_id == case.expected_template_id
    if case.bucket == UNMATCHED_BUCKET:
        return status == "unmatched" and template_id == -1
    if case.bucket == NOT_FULL_MATCH_BUCKET:
        return status != "matched"
    raise ValueError(f"Unsupported bucket: {case.bucket}")


def _expected_status(bucket: str) -> str:
    if bucket == MATCHED_BUCKET:
        return "matched"
    if bucket == PARTIAL_BUCKET:
        return "partial"
    if bucket == UNMATCHED_BUCKET:
        return "unmatched"
    if bucket == NOT_FULL_MATCH_BUCKET:
        return "not_matched_fully"
    raise ValueError(f"Unsupported bucket: {bucket}")
