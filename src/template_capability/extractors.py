from __future__ import annotations

import re
from typing import Any


IP_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
TOPN_RE = re.compile(r"(?:top\s*|前)(\d+)", re.IGNORECASE)

REGION_MAP = {
    "北京": "region_bj",
    "上海": "region_sh",
    "广州": "region_gz",
    "深圳": "region_sz",
    "华东": "east_cn",
    "华南": "south_cn",
    "华北": "north_cn",
    "华中": "central_cn",
    "西北": "northwest_cn",
    "西南": "southwest_cn",
}


def normalize_text(text: str) -> str:
    """模板工程只做轻量标准化，不做语义改写。"""
    text = text.strip().lower()
    for token in ["，", "。", "？", "！"]:
        text = text.replace(token, " ")
    return " ".join(text.split())


def extract_slots(text: str, timezone: str = "Asia/Shanghai") -> dict[str, Any]:
    """抽取模板匹配所需的高频稳定槽位。"""
    slots: dict[str, Any] = {}
    time_range = _extract_time_range(text, timezone)
    if time_range:
        slots["time_range"] = time_range
    topn = _extract_topn(text)
    if topn is not None:
        slots["topn"] = topn
    severity = _extract_severity(text)
    if severity:
        slots["severity"] = severity
    object_scope = _extract_object_scope(text)
    if object_scope:
        slots["object_scope"] = object_scope
    metric = _extract_metric(text)
    if metric:
        slots["metric"] = metric
    protocol = _extract_protocol(text)
    if protocol:
        slots["protocol"] = protocol
    region_id = _extract_region_id(text)
    if region_id:
        slots["region_id"] = region_id
    device_id = _extract_device_id(text)
    if device_id:
        slots["device_id"] = device_id
    return slots


def _extract_time_range(text: str, timezone: str) -> dict[str, Any] | None:
    mapping = {
        "近24小时": "last_24h",
        "24小时": "last_24h",
        "近7天": "last_7d",
        "近30天": "last_30d",
        "近90天": "last_90d",
        "今天": "today",
        "昨天": "yesterday",
    }
    for token, preset in mapping.items():
        if token in text:
            return {
                "mode": "relative",
                "preset": preset,
                "timezone": timezone,
                "original_text": token,
            }
    return None


def _extract_topn(text: str) -> int | None:
    match = TOPN_RE.search(text)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    if 0 < value <= 1000:
        return value
    return None


def _extract_severity(text: str) -> str | None:
    if "严重" in text or "critical" in text:
        return "critical"
    if "次严重" in text or "major" in text:
        return "major"
    if "一般" in text or "minor" in text:
        return "minor"
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
    if "设备" in text:
        return "device"
    if "区域" in text or "地市" in text:
        return "network"
    if "bgp" in text or "ospf" in text or "isis" in text:
        return "network"
    return None


def _extract_metric(text: str) -> str | None:
    mapping = {
        "丢包率": "packet_loss",
        "丢包": "packet_loss",
        "时延": "latency",
        "延迟": "latency",
        "抖动": "jitter",
        "cpu": "cpu_usage",
        "内存": "memory_usage",
        "错误包": "error_packet",
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
    return None


def _extract_region_id(text: str) -> str | None:
    for region, region_id in REGION_MAP.items():
        if region in text:
            return region_id
    return None


def _extract_device_id(text: str) -> str | None:
    match = IP_RE.search(text)
    if not match:
        return None
    # 独立模板工程没有远程 resolver，直接把 IP 作为设备标识使用。
    return match.group(0)

