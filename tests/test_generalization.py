import pytest

from template_capability.engine import TemplateCapabilityEngine


ENGINE = TemplateCapabilityEngine.from_file("configs/templates.json")


@pytest.mark.parametrize(
    ("text", "template_id", "status"),
    [
        ("过去24小时接口错包告警前10名", "alarm.interface.error.topn", "matched"),
        ("前10名的接口错误包告警，统计范围近24小时", "alarm.interface.error.topn", "matched"),
        ("想看华东近7天接口错误包告警top20", "alarm.interface.error.topn", "matched"),
        ("昨天华东离线设备数", "device.offline.count", "matched"),
        ("华东昨天掉线设备有多少", "device.offline.count", "matched"),
        ("统计一下近24小时广州离线设备数量", "device.offline.count", "matched"),
        ("近7天各区域丢包率排名Top10", "network.packet_loss.rank.topn", "matched"),
        ("过去24小时地区丢包排行前10", "network.packet_loss.rank.topn", "matched"),
        ("昨天地市丢包率Top5", "network.packet_loss.rank.topn", "matched"),
        ("今天广州区域严重告警数量", "alarm.critical.count", "matched"),
        ("北京近7天严重告警数", "alarm.critical.count", "matched"),
        ("华东昨天critical告警有多少", "alarm.critical.count", "matched"),
        ("查询最近cpu大于80的设备列表", "device.cpu.over.list", "matched"),
        ("列出华东cpu超过85的设备", "device.cpu.over.list", "matched"),
        ("查询最近内存大于75的设备列表", "device.memory.over.list", "matched"),
        ("列出华南内存超过70的设备", "device.memory.over.list", "matched"),
        ("查询最近cpu大于80且内存大于70的设备列表", "device.cpu.memory.over.list", "matched"),
        ("最近7天上海cpu利用率超过80且内存使用率超过70的设备有哪些", "device.cpu.memory.over.list", "matched"),
        ("查询近24小时cpu大于80 内存大于70 磁盘大于85的设备列表", "device.cpu.memory.disk.over.list", "matched"),
        ("最近cpu高于90 内存高于80 磁盘高于85的设备有哪些", "device.cpu.memory.disk.over.list", "matched"),
        ("查询cup大余88的设别列表", "device.cpu.over.list", "matched"),
        ("接口错误包告警排行", "alarm.interface.error.topn", "partial"),
        ("广州严重告警数", "alarm.critical.count", "partial"),
        ("查询最近cpu大于80的设备", "device.cpu.over.list", "partial"),
        ("查询最近内存大于75的设备", "device.memory.over.list", "partial"),
        ("查询最近cpu大于80且内存大于70的设备", "device.cpu.memory.over.list", "partial"),
        ("查询近24小时cpu大于80 内存大于70 磁盘大于85的设备", "device.cpu.memory.disk.over.list", "partial"),
    ],
)
def test_template_generalization(text: str, template_id: str, status: str):
    payload = ENGINE.match(text).to_dict()
    assert payload["template_id"] == template_id
    assert payload["status"] == status


@pytest.mark.parametrize(
    "text",
    [
        "帮我写一段年终总结",
        "分析接口错误包告警的根因",
        "生成昨天华东离线设备报告",
        "预测下周丢包率走势",
        "给我cpu大于80设备的分析结论",
        "请输出cpu和内存异常设备的优化建议",
    ],
)
def test_non_metric_or_analysis_queries_return_minus_one(text: str):
    payload = ENGINE.match(text).to_dict()
    assert payload["template_id"] == -1
    assert payload["status"] == "unmatched"
