from chat_pre_check.infrastructure.extractors.rule_extractors import extract_entities


def test_extract_entities_basic():
    entities = extract_entities("查近24小时核心网告警top10", timezone="Asia/Shanghai")
    assert entities["topn"] == 10
    assert entities["object_scope"] == "core_network"
    assert entities["time_range"]["preset"] == "last_24h"


def test_extract_entities_ip_and_intent():
    entities = extract_entities("近7天设备10.2.3.4告警趋势", timezone="Asia/Shanghai")
    assert entities["device_ip"] == "10.2.3.4"
    assert entities["intent"] == "trend"


def test_extract_metric_protocol_threshold():
    entities = extract_entities("近24小时BGP链路丢包率大于5%告警Top10", timezone="Asia/Shanghai")
    assert entities["metric"] == "packet_loss"
    assert entities["protocol"] == "bgp"
    assert entities["threshold_percent"] == 5.0
