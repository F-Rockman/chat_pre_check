from __future__ import annotations

import re
from functools import lru_cache

from template_capability.extractors import normalize_text
from template_capability.models import TextMatchRule


def match_text_rule(normalized_text: str, rule: TextMatchRule) -> bool:
    """在已标准化文本上执行匹配。"""
    normalized_term = _normalize_term(rule.term)
    if not normalized_term:
        return False
    if rule.match_mode == "exact":
        return normalized_text == normalized_term
    if rule.match_mode == "whole_word":
        return bool(_whole_word_pattern(normalized_term).search(normalized_text))
    return normalized_term in normalized_text


@lru_cache(maxsize=4096)
def _normalize_term(term: str) -> str:
    return normalize_text(term)


@lru_cache(maxsize=4096)
def _whole_word_pattern(normalized_term: str) -> re.Pattern[str]:
    # 这里用空白边界定义 whole_word，适合英文缩写、编码、设备名等 token 化表达。
    return re.compile(rf"(?<!\S){re.escape(normalized_term)}(?!\S)")
