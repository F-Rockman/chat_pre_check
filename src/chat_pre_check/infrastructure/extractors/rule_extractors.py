from __future__ import annotations

import re
from typing import Any


IP_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
TOPN_RE = re.compile(r"(?:top\s*|前)(\d+)", re.IGNORECASE)
PERCENT_RE = re.compile(r"(?:>|大于|超过)\s*(\d+(?:\.\d+)?)\s*%")


def extract_entities(text: str, timezone: str) -> dict[str, Any]:
    """规则抽取入口：适合高频、稳定、可解释的轻量槽位。"""
    entities: dict[str, Any] = {}
    entities["time_range"] = _extract_time_range(text, timezone)
    entities["topn"] = _extract_topn(text)
    entities["severity"] = _extract_severity(text)
    entities["alarm_status"] = _extract_alarm_status(text)
    entities["object_scope"] = _extract_object_scope(text)
    entities["device_ip"] = _extract_ip(text)
    entities["region_hint"] = _extract_region_hint(text)
    entities["intent"] = _extract_intent(text)
    entities["metric"] = _extract_metric(text)
    entities["protocol"] = _extract_protocol(text)
    entities["threshold_percent"] = _extract_threshold_percent(text)
    return {key: value for key, value in entities.items() if value is not None}


def _extract_time_range(text: str, timezone: str) -> dict[str, Any] | None:
    """抽取相对时间范围，统一为 preset 表达。"""
    mapping = {
        "近24小时": "last_24h",
        "24小时": "last_24h",
        "近7天": "last_7d",
        "近14天": "last_14d",
        "近30天": "last_30d",
        "近90天": "last_90d",
        "今天": "today",
        "昨天": "yesterday",
        "本周": "this_week",
    }
    for token, preset in mapping.items():
        if token in text:
            return {
                "mode": "relative",
                "preset": preset,
                "timezone": timezone,
                "original_text": token,
                "confidence": 0.95,
            }
    return None


def _extract_topn(text: str) -> int | None:
    """抽取 TopN 数值。"""
    match = TOPN_RE.search(text)
    if not match:
        return None
    try:
        value = int(match.group(1))
        if 0 < value <= 1000:
            return value
    except ValueError:
        return None
    return None


def _extract_severity(text: str) -> str | None:
    if "严重" in text or "critical" in text:
        return "critical"
    if "p1" in text:
        return "critical"
    if "次严重" in text or "major" in text:
        return "major"
    if "p2" in text:
        return "major"
    if "一般" in text or "minor" in text:
        return "minor"
    if "p3" in text:
        return "minor"
    return None


def _extract_alarm_status(text: str) -> str | None:
    if "未恢复" in text or "active" in text:
        return "active"
    if "已恢复" in text or "closed" in text:
        return "closed"
    return None


def _extract_object_scope(text: str) -> str | None:
    if "全网" in text:
        return "network"
    if "核心网" in text:
        return "core_network"
    if "端口" in text:
        return "port"
    if "接口" in text:
        return "interface"
    if "链路" in text:
        return "link"
    if "基站" in text:
        return "site"
    if "设备" in text:
        return "device"
    if "区域" in text or "地市" in text:
        return "network"
    if "bgp" in text or "ospf" in text or "isis" in text:
        return "network"
    return None


def _extract_ip(text: str) -> str | None:
    match = IP_RE.search(text)
    if not match:
        return None
    return match.group(0)


def _extract_region_hint(text: str) -> str | None:
    for region in [
        "北京",
        "上海",
        "广州",
        "深圳",
        "华东",
        "华南",
        "华北",
        "华中",
        "西北",
        "西南",
    ]:
        if region in text:
            return region
    return None


def _extract_intent(text: str) -> str | None:
    if "趋势" in text:
        return "trend"
    if "离线设备数" in text or "离线设备数量" in text:
        return "offline_count"
    if "关联率" in text or "相关性" in text:
        return "analysis"
    if "top" in text or "前" in text:
        return "topn"
    if "根因" in text:
        return "root_cause"
    if "预测" in text:
        return "forecast"
    return None


def _extract_metric(text: str) -> str | None:
    """抽取常见指标名并映射到标准 metric。"""
    mapping = {
        "丢包率": "packet_loss",
        "丢包": "packet_loss",
        "时延": "latency",
        "延迟": "latency",
        "抖动": "jitter",
        "cpu": "cpu_usage",
        "内存": "memory_usage",
        "带宽": "bandwidth_usage",
        "吞吐": "throughput",
        "错误包": "error_packet",
        "恢复时长": "recovery_duration",
    }
    lowered = text.lower()
    for keyword, metric in mapping.items():
        if keyword in lowered:
            return metric
    return None


def _extract_protocol(text: str) -> str | None:
    lowered = text.lower()
    if "bgp" in lowered:
        return "bgp"
    if "ospf" in lowered:
        return "ospf"
    if "isis" in lowered:
        return "isis"
    if "mpls" in lowered:
        return "mpls"
    return None


def _extract_threshold_percent(text: str) -> float | None:
    match = PERCENT_RE.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if 0 <= value <= 100:
        return value
    return None
