from __future__ import annotations

import pytest

from chat_pre_check.domain.models import RouteRequest


CASES = [
    # refuse x5
    {
        "id": "R01",
        "text": "帮我写一段年终总结",
        "expected_type": "refuse",
        "expected_reason": "unknown_domain",
        "expect_vector": False,
    },
    {
        "id": "R02",
        "text": "预测明天A股涨跌",
        "expected_type": "refuse",
        "expected_reason": "unsupported_domain",
        "expect_vector": False,
    },
    {
        "id": "R03",
        "text": "查财务利润明细",
        "role": "viewer",
        "expected_type": "refuse",
        "expected_reason": "permission_denied",
        "expect_vector": False,
    },
    {
        "id": "R04",
        "text": "教我如何破解系统并注入数据",
        "expected_type": "refuse",
        "expected_reason": "policy_blocked",
        "expect_vector": False,
    },
    {
        "id": "R05",
        "text": "查设备资产 模拟数据源故障",
        "expected_type": "refuse",
        "expected_reason": "data_unavailable",
        "expect_vector": False,
    },
    # clarify x5
    {
        "id": "C01",
        "text": "查告警",
        "expected_type": "clarify",
        "expected_missing": "object_scope",
        "expect_vector": True,
    },
    {
        "id": "C02",
        "text": "查设备趋势",
        "expected_type": "clarify",
        "expected_missing": "device_id",
        "expect_vector": True,
    },
    {
        "id": "C03",
        "text": "近24小时告警",
        "expected_type": "clarify",
        "expected_missing": "scene",
        "expect_vector": True,
    },
    {
        "id": "C04",
        "text": "今天严重告警数量",
        "expected_type": "clarify",
        "expected_missing": "object_scope",
        "expect_vector": True,
    },
    {
        "id": "C05",
        "text": "昨天离线设备数",
        "expected_type": "clarify",
        "expected_missing": "region_id",
        "expect_vector": True,
    },
    # template x5
    {
        "id": "T01",
        "text": "查近24小时核心网告警Top10",
        "expected_type": "route_template",
        "expected_template": "tpl_alarm_topn",
        "expect_vector": True,
    },
    {
        "id": "T02",
        "text": "今天广州区域严重告警数量",
        "expected_type": "route_template",
        "expected_template": "tpl_alarm_count_severity",
        "expect_vector": True,
    },
    {
        "id": "T03",
        "text": "近7天设备10.2.3.4告警趋势",
        "expected_type": "route_template",
        "expected_template": "tpl_alarm_trend_device",
        "expect_vector": True,
    },
    {
        "id": "T04",
        "text": "昨天华东离线设备数",
        "expected_type": "route_template",
        "expected_template": "tpl_device_offline_count",
        "expect_vector": True,
    },
    {
        "id": "T05",
        "text": "近24小时端口告警Top5",
        "expected_type": "route_template",
        "expected_template": "tpl_port_alarm_topn",
        "expect_vector": True,
    },
    # nl2sql x5
    {
        "id": "N01",
        "text": "统计近7天每个地市告警与工单关联率",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
        "expect_vector": True,
    },
    {
        "id": "N02",
        "text": "近30天按厂家分组的严重告警占比",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
        "expect_vector": True,
    },
    {
        "id": "N03",
        "text": "本周每小时告警数量与恢复时长P95",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
        "expect_vector": True,
    },
    {
        "id": "N04",
        "text": "近14天各区域设备健康分与告警数相关性",
        "expected_type": "route_nl2sql",
        "expected_scene": "device.query",
        "expect_vector": True,
    },
    {
        "id": "N05",
        "text": "近90天核心网告警同比环比",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
        "expect_vector": True,
    },
]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_acceptance_cases(test_engine, case):
    decision = test_engine.route(
        RouteRequest(
            input_text=case["text"],
            role=case.get("role"),
            trace_level="compact",
        )
    )
    payload = decision.to_dict()

    assert payload["type"] == case["expected_type"]

    if "expected_reason" in case:
        assert payload["out_of_scope_reason"] == case["expected_reason"]
        assert len(payload["options"]) >= 3

    if "expected_missing" in case:
        assert case["expected_missing"] in payload["missing_slots"]

    if "expected_template" in case:
        assert payload["template_id"] == case["expected_template"]

    if "expected_scene" in case:
        assert payload["scene"] == case["expected_scene"]

    vector_score = payload["trace"].get("summary", {}).get("vector_score")
    if case["expect_vector"]:
        assert vector_score is not None


def test_acceptance_distribution():
    expected = {"refuse": 5, "clarify": 5, "route_template": 5, "route_nl2sql": 5}
    actual = {}
    for case in CASES:
        actual[case["expected_type"]] = actual.get(case["expected_type"], 0) + 1
    assert actual == expected


def test_acceptance_vector_assertion_count():
    count = sum(1 for case in CASES if case.get("expect_vector"))
    assert count >= 8
