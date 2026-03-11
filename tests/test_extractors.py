from template_capability.config import load_template_config
from template_capability.extractors import build_slot_registry, normalize_text


def build_registry():
    config = load_template_config("configs/templates.json")
    return build_slot_registry(config.slot_extractors)


def test_extract_slots_for_interface_topn_query():
    slots = build_registry().extract(normalize_text("过去24小时接口错包告警前10名"))
    assert slots["time_range"]["preset"] == "last_24h"
    assert slots["topn"] == 10
    assert slots["entity_type"] == "interface"
    assert slots["metric"] == "error_packet"
    assert slots["query_operator"] == "topn"


def test_extract_slots_for_count_query():
    slots = build_registry().extract(normalize_text("昨天华东离线设备有多少"))
    assert slots["time_range"]["preset"] == "yesterday"
    assert slots["region_id"] == "east_cn"
    assert slots["entity_type"] == "device"
    assert slots["metric"] == "offline_count"
    assert slots["query_operator"] == "count"


def test_extract_slots_for_alarm_count_query():
    slots = build_registry().extract(normalize_text("今天广州严重告警数量"))
    assert slots["time_range"]["preset"] == "today"
    assert slots["region_id"] == "region_gz"
    assert slots["metric"] == "alarm_count"
    assert slots["severity"] == "critical"


def test_extract_slots_for_cpu_threshold_list_query():
    slots = build_registry().extract(normalize_text("查询最近cpu大于80的设备列表"))
    assert slots["time_range"]["preset"] == "recent"
    assert slots["entity_type"] == "device"
    assert slots["metric"] == "cpu_usage"
    assert slots["query_operator"] == "list"
    assert slots["cpu_threshold"] == 80.0


def test_extract_slots_for_multi_threshold_list_query():
    slots = build_registry().extract(
        normalize_text("查询近24小时cpu大于80 内存大于70 磁盘大于85的设备列表")
    )
    assert slots["time_range"]["preset"] == "last_24h"
    assert slots["cpu_threshold"] == 80.0
    assert slots["memory_threshold"] == 70.0
    assert slots["disk_threshold"] == 85.0
    assert slots["query_operator"] == "list"


def test_extract_slots_tolerates_common_cpu_and_device_typos():
    slots = build_registry().extract(normalize_text("查询cup大余88的设别列表"))
    assert slots["entity_type"] == "device"
    assert slots["metric"] == "cpu_usage"
    assert slots["query_operator"] == "list"
    assert slots["cpu_threshold"] == 88.0
