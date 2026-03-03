from __future__ import annotations

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.domain.enums import OutOfScopeReason
from chat_pre_check.domain.models import RequestContext


def _service() -> RecommendationService:
    return RecommendationService(
        scenes=[],
        templates=[
            {
                "scene_id": "alarm.query",
                "examples": ["近24小时核心网告警Top10"],
            },
            {
                "scene_id": "device.query",
                "examples": ["近24小时设备CPU利用率Top10"],
            },
            {
                "scene_id": "finance.query",
                "examples": ["查看财务利润趋势"],
            },
        ],
        cases=[
            {
                "scene_id": "alarm.query",
                "recommended_actions": [
                    {
                        "label": "近7天告警趋势",
                        "intent": "alarm.query",
                        "preset_slots": {},
                        "need_followup_slots": [],
                    }
                ],
            }
        ],
    )


def test_refuse_options_policy_blocked_contains_capability_list() -> None:
    service = _service()
    ctx = RequestContext(input_text="test")
    options = service.refuse_options(ctx, OutOfScopeReason.POLICY_BLOCKED, limit=4)
    assert options
    assert any(item.intent == "capability.list" for item in options)


def test_refuse_options_permission_denied_filters_sensitive_labels() -> None:
    service = _service()
    ctx = RequestContext(input_text="test", scene="alarm.query")
    options = service.refuse_options(ctx, OutOfScopeReason.PERMISSION_DENIED, limit=5)
    labels = [item.label for item in options]
    assert labels
    assert all("财务" not in label for label in labels)
    assert all("利润" not in label for label in labels)


def test_refuse_options_out_of_seed_scope_prefers_scene_templates() -> None:
    service = _service()
    ctx = RequestContext(input_text="查告警", scene="alarm.query")
    options = service.refuse_options(ctx, OutOfScopeReason.OUT_OF_SEED_SCOPE, limit=3)
    assert options
    assert options[0].intent == "alarm.query"
