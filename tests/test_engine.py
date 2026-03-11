import json

from template_capability.engine import TemplateCapabilityEngine


def build_engine() -> TemplateCapabilityEngine:
    return TemplateCapabilityEngine.from_file("configs/templates.json")


def test_match_interface_alarm_topn():
    payload = build_engine().match("近24小时接口错误包告警Top10").to_dict()
    assert payload["template_id"] == "alarm.interface.error.topn"
    assert payload["status"] == "matched"


def test_match_device_cpu_over_list_template():
    payload = build_engine().match("查询最近cpu大于80的设备列表").to_dict()
    assert payload["template_id"] == "device.cpu.over.list"
    assert payload["status"] == "matched"
    assert payload["slots"]["cpu_threshold"] == 80.0


def test_match_device_cpu_memory_over_list_template():
    payload = build_engine().match("查询最近cpu大于80且内存大于70的设备列表").to_dict()
    assert payload["template_id"] == "device.cpu.memory.over.list"
    assert payload["status"] == "matched"
    assert payload["slots"]["cpu_threshold"] == 80.0
    assert payload["slots"]["memory_threshold"] == 70.0


def test_match_device_cpu_memory_disk_over_list_template():
    payload = build_engine().match("查询近24小时cpu大于80 内存大于70 磁盘大于85的设备列表").to_dict()
    assert payload["template_id"] == "device.cpu.memory.disk.over.list"
    assert payload["status"] == "matched"


def test_partial_match_when_required_slot_missing():
    payload = build_engine().match("近24小时接口错误包告警").to_dict()
    assert payload["template_id"] == "alarm.interface.error.topn"
    assert payload["status"] == "partial"
    assert "topn" in payload["missing_slots"]


def test_partial_match_for_device_list_without_list_intent():
    payload = build_engine().match("查询最近cpu大于80的设备").to_dict()
    assert payload["template_id"] == "device.cpu.over.list"
    assert payload["status"] == "partial"
    assert "query_operator" in payload["missing_slots"]


def test_unmatched_for_non_metric_query():
    payload = build_engine().match("帮我写一段巡检周报").to_dict()
    assert payload["template_id"] == -1
    assert payload["status"] == "unmatched"


def test_unmatched_payload_is_json_serializable():
    payload = build_engine().match("帮我写一段巡检周报").to_dict()
    json.dumps(payload, ensure_ascii=False)
