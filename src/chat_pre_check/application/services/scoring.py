from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from typing import Any


TOKEN_SPLIT_RE = re.compile(r"[\s,，。？！!?:：;；、/\\|]+")


def tokenize(text: str) -> set[str]:
    """简单分词：用于关键词重叠计算，不追求 NLP 完整性。"""
    return {token for token in TOKEN_SPLIT_RE.split(text.lower()) if token}


def keyword_overlap_score(text: str, keywords: list[str]) -> float:
    """关键词覆盖率分数，范围 [0,1]。"""
    if not keywords:
        return 0.0
    text_tokens = tokenize(text)
    if not text_tokens:
        return 0.0
    matches = sum(1 for keyword in keywords if keyword.lower() in text_tokens or keyword in text)
    return min(1.0, matches / max(1, len(keywords)))


def example_similarity_score(text: str, examples: list[str]) -> float:
    """示例相似度分数，取与任一示例的最大编辑相似比。"""
    if not examples:
        return 0.0
    score = 0.0
    for sample in examples:
        ratio = SequenceMatcher(None, text, sample.lower()).ratio()
        score = max(score, ratio)
    return float(score)


def entity_coverage_score(required_slots: list[str], slots: dict[str, Any]) -> float:
    """必填槽位命中率。"""
    if not required_slots:
        return 1.0
    present = 0
    for slot in required_slots:
        value = slots.get(slot)
        if value is not None and value != "":
            present += 1
    return present / len(required_slots)


def slot_fit_score(slot_schema: dict[str, Any], slots: dict[str, Any]) -> float:
    """槽位拟合分：必填为主，可选为辅。"""
    required = slot_schema.get("required", [])
    optional = slot_schema.get("optional", [])
    if not required and not optional:
        return 1.0
    req_score = entity_coverage_score(required, slots)
    if not optional:
        return req_score
    optional_hit = sum(1 for slot in optional if slots.get(slot) not in (None, ""))
    optional_score = optional_hit / len(optional)
    return 0.8 * req_score + 0.2 * optional_score


def clamp_score(score: float) -> float:
    """分数钳制到 [0,1]，并兜底 NaN。"""
    if math.isnan(score):
        return 0.0
    return max(0.0, min(1.0, score))


def weighted_score(parts: dict[str, float], weights: dict[str, float]) -> float:
    """按权重融合多路分数。"""
    total = 0.0
    for key, weight in weights.items():
        total += clamp_score(parts.get(key, 0.0)) * weight
    return clamp_score(total)
