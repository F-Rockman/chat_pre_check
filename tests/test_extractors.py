from template_capability.extractors import extract_slots


def test_extract_slots_alarm_topn():
    slots = extract_slots("查近24小时核心网告警top10")
    assert slots["topn"] == 10
    assert slots["object_scope"] == "core_network"
    assert slots["time_range"]["preset"] == "last_24h"


def test_extract_slots_device_ip_and_metric():
    slots = extract_slots("近7天设备10.2.3.4告警趋势")
    assert slots["device_id"] == "10.2.3.4"
    assert slots["time_range"]["preset"] == "last_7d"


def test_extract_slots_region_metric_protocol():
    slots = extract_slots("近24小时华东BGP丢包率Top10")
    assert slots["region_id"] == "east_cn"
    assert slots["metric"] == "packet_loss"
    assert slots["protocol"] == "bgp"

