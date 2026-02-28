from chat_pre_check.application.services.scoring import (
    entity_coverage_score,
    keyword_overlap_score,
    weighted_score,
)


def test_keyword_overlap_score():
    score = keyword_overlap_score("查 告警 top10", ["告警", "top", "趋势"])
    assert score > 0.6


def test_entity_coverage_score():
    score = entity_coverage_score(["object_scope", "time_range"], {"time_range": "last_24h"})
    assert score == 0.5


def test_weighted_score():
    score = weighted_score({"rule": 1.0, "vector": 0.5, "entity": 0.0}, {"rule": 0.35, "vector": 0.45, "entity": 0.2})
    assert 0.0 <= score <= 1.0
