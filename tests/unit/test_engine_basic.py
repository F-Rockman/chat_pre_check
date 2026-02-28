from chat_pre_check.domain.enums import DecisionType
from chat_pre_check.domain.models import RouteRequest


def test_engine_returns_decision(test_engine):
    decision = test_engine.route(RouteRequest(input_text="查告警"))
    assert decision.type in {
        DecisionType.REFUSE,
        DecisionType.CLARIFY,
        DecisionType.ROUTE_TEMPLATE,
        DecisionType.ROUTE_NL2SQL,
    }
    assert "request_id" in decision.trace
