from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from typing import Any


TOKEN_SPLIT_RE = re.compile(r"[\s,，。？！!?:：;；、/\\|]+")


def tokenize(text: str) -> set[str]:
    """轻量分词，服务于关键词覆盖计算。"""
    return {token for token in TOKEN_SPLIT_RE.split(text.lower()) if token}


def keyword_overlap_score(text: str, keywords: list[str]) -> float:
    """关键词命中率，适合高频稳定模板。"""
    if not keywords:
        return 0.0
    text_tokens = tokenize(text)
    if not text_tokens:
        return 0.0
    matches = sum(1 for keyword in keywords if keyword.lower() in text_tokens or keyword in text)
    return min(1.0, matches / max(1, len(keywords)))


def example_similarity_score(text: str, examples: list[str]) -> float:
    """示例文本的最大相似度，作为模板语义相近度近似。"""
    if not examples:
        return 0.0
    score = 0.0
    for sample in examples:
        score = max(score, SequenceMatcher(None, text, sample.lower()).ratio())
    return float(score)


def entity_coverage_score(required_slots: list[str], slots: dict[str, Any]) -> float:
    """当前槽位对模板必填参数的覆盖率。"""
    if not required_slots:
        return 1.0
    present = 0
    for slot in required_slots:
        if slots.get(slot) not in (None, ""):
            present += 1
    return present / len(required_slots)


def slot_fit_score(slot_schema: dict[str, Any], slots: dict[str, Any]) -> float:
    """槽位拟合分：必填优先，可选次之。"""
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
    """把异常值、越界值统一收敛到 [0,1]。"""
    if math.isnan(score):
        return 0.0
    return max(0.0, min(1.0, score))


def weighted_score(parts: dict[str, float], weights: dict[str, float]) -> float:
    """模板总分融合。"""
    total = 0.0
    for key, weight in weights.items():
        total += clamp_score(parts.get(key, 0.0)) * weight
    return clamp_score(total)

