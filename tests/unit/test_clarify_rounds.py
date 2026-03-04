from __future__ import annotations

from chat_pre_check.domain.enums import DecisionType
from chat_pre_check.domain.models import RouteRequest


def test_clarify_round_increases_when_missing_slots(test_engine) -> None:
    decision = test_engine.route(RouteRequest(input_text="查告警"))
    payload = decision.to_dict()
    assert decision.type == DecisionType.CLARIFY
    assert payload["clarify_round"] == 1
    assert payload["max_clarify_round"] == 5
    assert payload["next_action"] == "ask_slot"


def test_exceed_clarify_rounds_refuses(test_engine) -> None:
    decision = test_engine.route(
        RouteRequest(
            input_text="查告警",
            context={
                "clarify_round": 5,
                "max_clarify_round": 5,
            },
        )
    )
    payload = decision.to_dict()
    assert decision.type == DecisionType.REFUSE
    assert payload["clarify_round"] == 5
    assert payload["max_clarify_round"] == 5
    assert payload["next_action"] == "refuse"

