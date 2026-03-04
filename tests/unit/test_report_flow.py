from __future__ import annotations

from chat_pre_check.domain.enums import DecisionType
from chat_pre_check.domain.models import RouteRequest


def test_report_request_routes_to_report_flow(test_engine) -> None:
    decision = test_engine.route(RouteRequest(input_text="帮我生成巡检报告"))
    payload = decision.to_dict()
    assert decision.type == DecisionType.ROUTE_REPORT
    assert payload["flow_type"] == "report"
    assert payload["scene"] == "report.inspect"
    assert payload["next_action"] == "route_report"

