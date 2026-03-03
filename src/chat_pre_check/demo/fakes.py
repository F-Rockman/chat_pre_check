from __future__ import annotations

from chat_pre_check.domain.models import Candidate, SearchHit


class DemoDeviceResolver:
    """演示设备解析器：返回固定候选，便于可重复测试。"""

    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        text = text.lower()
        if "10.2.3.4" in text:
            return [
                Candidate("dev_10_2_3_4", "设备10.2.3.4", 0.95),
                Candidate("dev_10_2_3_5", "设备10.2.3.5", 0.70),
            ][:topk]
        if "r1" in text or "核心路由器" in text:
            return [
                Candidate("dev_r1", "核心路由器R1", 0.90),
                Candidate("dev_r2", "核心路由器R2", 0.74),
            ][:topk]
        return []


class DemoRegionResolver:
    """演示区域解析器：返回固定候选，便于可重复测试。"""

    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        mapping = {
            "广州": ("region_gz", "广州"),
            "北京": ("region_bj", "北京"),
            "华东": ("east_cn", "华东"),
            "华南": ("south_cn", "华南"),
            "华北": ("north_cn", "华北"),
        }
        for keyword, (region_id, name) in mapping.items():
            if keyword in text:
                return [
                    Candidate(region_id, name, 0.94),
                    Candidate("region_other", "其他区域", 0.70),
                ][:topk]
        return []


class DemoVectorRetriever:
    """演示检索器：用规则模拟 scene/template/seed 召回。"""

    def search_scene(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        text = query_text.lower()
        hits: list[SearchHit] = []
        if "近24小时告警" in text and "top" not in text:
            hits = [
                SearchHit("scene_alarm_query", 0.93, {"scene_id": "alarm.query"}),
                SearchHit("scene_alarm_analysis", 0.88, {"scene_id": "alarm.analysis"}),
            ]
        elif any(k in text for k in ["接口", "bgp", "ospf", "isis", "flap", "错误包"]):
            hits = [
                SearchHit("scene_alarm_query", 0.95, {"scene_id": "alarm.query"}),
                SearchHit("scene_alarm_analysis", 0.68, {"scene_id": "alarm.analysis"}),
            ]
        elif "健康分" in text:
            hits = [
                SearchHit("scene_device_query", 0.95, {"scene_id": "device.query"}),
                SearchHit("scene_alarm_analysis", 0.75, {"scene_id": "alarm.analysis"}),
            ]
        elif any(
            k in text
            for k in ["丢包", "时延", "延迟", "抖动", "带宽", "吞吐", "p95", "相关性", "占比", "环比", "同比"]
        ):
            hits = [
                SearchHit("scene_alarm_analysis", 0.95, {"scene_id": "alarm.analysis"}),
                SearchHit("scene_ticket_analysis", 0.60, {"scene_id": "ticket.analysis"}),
            ]
        elif any(k in text for k in ["cpu", "内存", "离线", "设备", "利用率"]):
            hits = [
                SearchHit("scene_device_query", 0.95, {"scene_id": "device.query"}),
                SearchHit("scene_alarm_query", 0.70, {"scene_id": "alarm.query"}),
            ]
        elif "工单" in text:
            hits = [
                SearchHit("scene_ticket_analysis", 0.94, {"scene_id": "ticket.analysis"}),
                SearchHit("scene_alarm_analysis", 0.90, {"scene_id": "alarm.analysis"}),
            ]
        elif "告警" in text:
            hits = [
                SearchHit("scene_alarm_query", 0.96, {"scene_id": "alarm.query"}),
                SearchHit("scene_alarm_analysis", 0.70, {"scene_id": "alarm.analysis"}),
            ]
        return hits[:topk]

    def search_template(
        self, scene_id: str, query_text: str, topk: int = 5
    ) -> list[SearchHit]:
        text = query_text.lower()
        hits: list[SearchHit] = []
        if scene_id == "alarm.query":
            if "核心网" in text and "top" in text:
                hits = [SearchHit("tpl_alarm_topn_hit", 0.95, {"template_id": "tpl_alarm_topn"})]
            elif "端口" in text and "top" in text:
                hits = [SearchHit("tpl_port_alarm_topn_hit", 0.95, {"template_id": "tpl_port_alarm_topn"})]
            elif "严重" in text and "数量" in text:
                hits = [
                    SearchHit(
                        "tpl_alarm_count_severity_hit",
                        0.94,
                        {"template_id": "tpl_alarm_count_severity"},
                    )
                ]
            elif "接口" in text and "top" in text:
                hits = [
                    SearchHit(
                        "tpl_interface_alarm_topn_hit",
                        0.95,
                        {"template_id": "tpl_interface_alarm_topn"},
                    )
                ]
            elif "bgp" in text and "top" in text:
                hits = [
                    SearchHit(
                        "tpl_bgp_flap_topn_hit",
                        0.95,
                        {"template_id": "tpl_bgp_flap_topn"},
                    )
                ]
        elif scene_id == "device.query":
            if "趋势" in text and "10.2.3.4" in text:
                hits = [
                    SearchHit(
                        "tpl_alarm_trend_device_hit",
                        0.95,
                        {"template_id": "tpl_alarm_trend_device"},
                    )
                ]
            elif "离线设备数" in text or "离线设备数量" in text:
                hits = [
                    SearchHit(
                        "tpl_device_offline_count_hit",
                        0.94,
                        {"template_id": "tpl_device_offline_count"},
                    )
                ]
            elif "cpu" in text and "top" in text:
                hits = [
                    SearchHit(
                        "tpl_device_cpu_hotspot_hit",
                        0.95,
                        {"template_id": "tpl_device_cpu_hotspot"},
                    )
                ]
        elif scene_id == "alarm.analysis":
            if "丢包率" in text and "top" in text:
                hits = [
                    SearchHit(
                        "tpl_packet_loss_region_rank_hit",
                        0.95,
                        {"template_id": "tpl_packet_loss_region_rank"},
                    )
                ]
        return hits[:topk]

    def search_seed_cases(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        text = query_text.lower()
        if any(k in text for k in ["告警", "设备", "丢包", "时延", "bgp", "cpu"]):
            return [
                SearchHit(
                    "seed_case_1",
                    0.92,
                    {
                        "case_id": "seed_alarm_topn_core_24h",
                        "scene_id": "alarm.query",
                        "label": "查近24小时核心网告警Top10",
                    },
                ),
                SearchHit(
                    "seed_case_2",
                    0.88,
                    {
                        "case_id": "seed_packet_loss_rank",
                        "scene_id": "alarm.analysis",
                        "label": "近7天各区域丢包率排名Top10",
                    },
                ),
            ][:topk]
        return []
