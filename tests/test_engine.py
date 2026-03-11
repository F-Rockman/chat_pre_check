from template_capability.engine import TemplateCapabilityEngine


def build_engine() -> TemplateCapabilityEngine:
    return TemplateCapabilityEngine.from_file("configs/templates.json")


def test_route_template_for_interface_alarm():
    decision = build_engine().route("近24小时接口错误包告警Top10")
    payload = decision.to_dict()
    assert payload["type"] == "route_template"
    assert payload["template_id"] == "tpl_interface_alarm_topn"


def test_clarify_when_template_hits_but_topn_missing():
    decision = build_engine().route("近24小时接口错误包告警")
    payload = decision.to_dict()
    assert payload["type"] == "clarify"
    assert "topn" in payload["missing_slots"]


def test_route_template_for_device_offline_count():
    decision = build_engine().route("昨天华东离线设备数")
    payload = decision.to_dict()
    assert payload["type"] == "route_template"
    assert payload["template_id"] == "tpl_device_offline_count"


def test_refuse_for_unrelated_text():
    decision = build_engine().route("帮我写一段年终总结")
    payload = decision.to_dict()
    assert payload["type"] == "refuse"
