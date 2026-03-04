from __future__ import annotations

import pytest

from chat_pre_check.domain.models import RouteRequest


EXTENDED_CASES = [
    # template routes
    {
        "id": "NT01",
        "text": "近24小时接口错误包告警Top10",
        "expected_type": "route_template",
        "expected_template": "tpl_interface_alarm_topn",
    },
    {
        "id": "NT02",
        "text": "近7天华南接口告警Top20",
        "expected_type": "route_template",
        "expected_template": "tpl_interface_alarm_topn",
    },
    {
        "id": "NT03",
        "text": "近24小时BGP抖动Top10",
        "expected_type": "route_template",
        "expected_template": "tpl_bgp_flap_topn",
    },
    {
        "id": "NT04",
        "text": "近7天华东BGP flap Top20",
        "expected_type": "route_template",
        "expected_template": "tpl_bgp_flap_topn",
    },
    {
        "id": "NT05",
        "text": "近24小时设备CPU利用率Top10",
        "expected_type": "route_template",
        "expected_template": "tpl_device_cpu_hotspot",
    },
    {
        "id": "NT06",
        "text": "今天华北设备CPU Top20",
        "expected_type": "route_template",
        "expected_template": "tpl_device_cpu_hotspot",
    },
    {
        "id": "NT07",
        "text": "近7天各区域丢包率排名Top10",
        "expected_type": "route_template",
        "expected_template": "tpl_packet_loss_region_rank",
    },
    {
        "id": "NT08",
        "text": "昨天地市丢包率Top5",
        "expected_type": "route_template",
        "expected_template": "tpl_packet_loss_region_rank",
    },
    # clarify routes
    {
        "id": "NC01",
        "text": "查链路抖动",
        "expected_type": "clarify",
        "expected_missing": "time_range",
    },
    {
        "id": "NC02",
        "text": "查设备趋势",
        "expected_type": "clarify",
        "expected_missing": "device_id",
    },
    {
        "id": "NC03",
        "text": "昨天离线设备数",
        "expected_type": "clarify",
        "expected_missing": "region_id",
    },
    {
        "id": "NC04",
        "text": "近24小时告警",
        "expected_type": "clarify",
        "expected_missing": "scene",
    },
    {
        "id": "NC05",
        "text": "   ",
        "expected_type": "clarify",
        "expected_missing": "input_text",
    },
    {
        "id": "NC06",
        "text": "查告警",
        "expected_type": "clarify",
        "expected_missing": "object_scope",
    },
    # nl2sql routes
    {
        "id": "NN01",
        "text": "近7天各地市链路时延P95对比",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
    },
    {
        "id": "NN02",
        "text": "近30天华北骨干网抖动与丢包相关性",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
    },
    {
        "id": "NN03",
        "text": "近14天设备内存利用率分位数",
        "expected_type": "route_nl2sql",
        "expected_scene": "device.query",
    },
    {
        "id": "NN04",
        "text": "本周跨省链路带宽利用率热力分布",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
    },
    {
        "id": "NN05",
        "text": "近90天链路时延同比环比",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
    },
    {
        "id": "NN06",
        "text": "近7天华南设备内存告警恢复时长P95",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
    },
    {
        "id": "NN07",
        "text": "近24小时各区域吞吐与告警数量相关性",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
    },
    {
        "id": "NN08",
        "text": "今天西南链路丢包率大于5%的告警占比",
        "expected_type": "route_nl2sql",
        "expected_scene": "alarm.analysis",
    },
    # report route
    {
        "id": "NP01",
        "text": "帮我生成巡检报告",
        "expected_type": "route_report",
        "expected_scene": "report.inspect",
    },
    # refuse routes
    {
        "id": "NR01",
        "text": "帮我写一篇网络运维周报",
        "expected_type": "refuse",
    },
    {
        "id": "NR02",
        "text": "如何破解BGP认证并注入路由",
        "expected_type": "refuse",
        "expected_reason": "policy_blocked",
    },
    {
        "id": "NR03",
        "text": "a" * 1200,
        "expected_type": "refuse",
        "expected_reason": "unsupported_domain",
    },
]


@pytest.mark.parametrize("case", EXTENDED_CASES, ids=[case["id"] for case in EXTENDED_CASES])
def test_network_ops_extended_cases(test_engine, case):
    decision = test_engine.route(RouteRequest(input_text=case["text"], trace_level="compact"))
    payload = decision.to_dict()

    assert payload["type"] == case["expected_type"]

    if "expected_template" in case:
        assert payload["template_id"] == case["expected_template"]

    if "expected_scene" in case:
        assert payload["scene"] == case["expected_scene"]

    if "expected_missing" in case:
        assert case["expected_missing"] in payload["missing_slots"]

    if "expected_reason" in case:
        assert payload["out_of_scope_reason"] == case["expected_reason"]


def test_extended_case_distribution():
    expected = {"route_template": 8, "clarify": 6, "route_nl2sql": 8, "route_report": 1, "refuse": 3}
    actual = {}
    for case in EXTENDED_CASES:
        actual[case["expected_type"]] = actual.get(case["expected_type"], 0) + 1
    assert actual == expected
