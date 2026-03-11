from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from template_capability.models import TemplateDefinition


TOKEN_RE = re.compile(r"[a-z0-9_.-]+|[\u4e00-\u9fff]+")
LOW_SIGNAL_SLOTS = {"time_range", "region_id"}
FILTER_SLOTS = {"topn", "severity", "device_id", "protocol"}


def mixed_terms(text: str) -> list[str]:
    """混合 token + char ngram，兼顾中文短句和提参变化。"""
    chunks = TOKEN_RE.findall(text.lower())
    terms: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        terms.append(chunk)
        if _contains_cjk(chunk):
            terms.extend(_char_ngrams(chunk, 2))
            if len(chunk) >= 3:
                terms.extend(_char_ngrams(chunk, 3))
        elif len(chunk) >= 4:
            terms.extend(_char_ngrams(chunk, 3))
    return terms or [text.lower()]


def sample_similarity_score(text: str, utterances: list[str]) -> float:
    """兼容旧调用方的便捷入口。"""
    if not utterances:
        return 0.0
    query_terms = set(mixed_terms(text))
    return sample_similarity_from_terms(query_terms, build_utterance_term_sets(utterances))


def build_utterance_term_sets(utterances: list[str]) -> list[set[str]]:
    """提前把模板示例问法切词，避免每次匹配都重复处理。"""
    return [set(mixed_terms(utterance)) for utterance in utterances if utterance]


def sample_similarity_from_terms(query_terms: set[str], utterance_term_sets: list[set[str]]) -> float:
    """用 Dice 风格的重叠率衡量 query 和示例问法的接近程度。"""
    if not query_terms:
        return 0.0
    best = 0.0
    for utterance_terms in utterance_term_sets:
        overlap = len(query_terms & utterance_terms)
        total = len(query_terms) + len(utterance_terms)
        if total == 0:
            continue
        score = (2.0 * overlap) / total
        best = max(best, score)
    return best


@dataclass(slots=True)
class BM25Index:
    """轻量 BM25 实现，用于模板候选召回。"""

    documents: dict[str, list[str]]
    k1: float = 1.5
    b: float = 0.75
    doc_term_freqs: dict[str, Counter[str]] = field(init=False, default_factory=dict)
    doc_lengths: dict[str, int] = field(init=False, default_factory=dict)
    avg_doc_length: float = field(init=False, default=0.0)
    doc_freqs: Counter[str] = field(init=False, default_factory=Counter)
    total_docs: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.doc_term_freqs = {
            doc_id: Counter(terms)
            for doc_id, terms in self.documents.items()
        }
        self.doc_lengths = {
            doc_id: sum(term_freq.values())
            for doc_id, term_freq in self.doc_term_freqs.items()
        }
        doc_count = max(1, len(self.documents))
        self.avg_doc_length = sum(self.doc_lengths.values()) / doc_count
        self.doc_freqs: Counter[str] = Counter()
        for term_freq in self.doc_term_freqs.values():
            for term in term_freq:
                self.doc_freqs[term] += 1
        self.total_docs = doc_count

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        query_terms = mixed_terms(query_text)
        results = [
            (doc_id, self._score_doc(query_terms, doc_id))
            for doc_id in self.documents
        ]
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:top_k]

    def _score_doc(self, query_terms: list[str], doc_id: str) -> float:
        term_freq = self.doc_term_freqs.get(doc_id, Counter())
        doc_length = self.doc_lengths.get(doc_id, 0)
        score = 0.0
        for term in query_terms:
            freq = term_freq.get(term)
            if not freq:
                continue
            doc_freq = self.doc_freqs.get(term, 0)
            idf = math.log(1 + (self.total_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (
                1 - self.b + self.b * doc_length / max(1.0, self.avg_doc_length)
            )
            score += idf * numerator / denominator
        return score


@dataclass(slots=True)
class BM25FieldIndex:
    """简化版 BM25F，对模板多字段分别建模后加权求和。"""

    documents: dict[str, dict[str, list[str]]]
    field_weights: dict[str, float]
    k1: float = 1.5
    b: float = 0.75
    doc_term_freqs: dict[str, dict[str, Counter[str]]] = field(init=False, default_factory=dict)
    doc_lengths: dict[str, dict[str, int]] = field(init=False, default_factory=dict)
    avg_field_lengths: dict[str, float] = field(init=False, default_factory=dict)
    field_doc_freqs: dict[str, Counter[str]] = field(init=False, default_factory=dict)
    total_docs: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.total_docs = max(1, len(self.documents))
        self.doc_term_freqs = {}
        self.doc_lengths = {}
        for doc_id, fields in self.documents.items():
            self.doc_term_freqs[doc_id] = {}
            self.doc_lengths[doc_id] = {}
            for field_name in self.field_weights:
                terms = fields.get(field_name, [])
                term_freq = Counter(terms)
                self.doc_term_freqs[doc_id][field_name] = term_freq
                self.doc_lengths[doc_id][field_name] = sum(term_freq.values())

        self.avg_field_lengths = {}
        self.field_doc_freqs = {}
        for field_name in self.field_weights:
            total_length = sum(
                self.doc_lengths[doc_id].get(field_name, 0)
                for doc_id in self.documents
            )
            self.avg_field_lengths[field_name] = total_length / self.total_docs
            doc_freqs: Counter[str] = Counter()
            for doc_id in self.documents:
                for term in self.doc_term_freqs[doc_id][field_name]:
                    doc_freqs[term] += 1
            self.field_doc_freqs[field_name] = doc_freqs

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        query_terms = mixed_terms(query_text)
        results = [
            (doc_id, self._score_doc(query_terms, doc_id))
            for doc_id in self.documents
        ]
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:top_k]

    def _score_doc(self, query_terms: list[str], doc_id: str) -> float:
        score = 0.0
        for field_name, field_weight in self.field_weights.items():
            score += field_weight * self._score_field(query_terms, doc_id, field_name)
        return score

    def _score_field(self, query_terms: list[str], doc_id: str, field_name: str) -> float:
        term_freq = self.doc_term_freqs.get(doc_id, {}).get(field_name, Counter())
        doc_length = self.doc_lengths.get(doc_id, {}).get(field_name, 0)
        avg_length = self.avg_field_lengths.get(field_name, 0.0)
        doc_freqs = self.field_doc_freqs.get(field_name, Counter())
        score = 0.0
        for term in query_terms:
            freq = term_freq.get(term)
            if not freq:
                continue
            doc_freq = doc_freqs.get(term, 0)
            idf = math.log(1 + (self.total_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (
                1 - self.b + self.b * doc_length / max(1.0, avg_length)
            )
            score += idf * numerator / denominator
        return score


def normalize_candidate_scores(items: list[tuple[str, float]]) -> dict[str, float]:
    """把不同召回路的原始分压到 0-1，方便后续融合。"""
    if not items:
        return {}
    top_score = max(score for _, score in items)
    if top_score <= 0:
        return {doc_id: 0.0 for doc_id, _ in items}
    return {doc_id: clamp_score(score / top_score) for doc_id, score in items}


def reciprocal_rank_fusion(
    rankings: list[list[tuple[str, float]]],
    *,
    rrf_k: int = 60,
) -> dict[str, float]:
    """RRF 只看 rank，不依赖各路原始分是否同尺度。"""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (doc_id, _) in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    if not fused:
        return {}
    top_score = max(fused.values())
    if top_score <= 0:
        return {doc_id: 0.0 for doc_id in fused}
    return {doc_id: clamp_score(score / top_score) for doc_id, score in fused.items()}


def slot_fit_score(template: TemplateDefinition, slots: dict[str, Any]) -> float:
    """衡量当前模板需要的槽位被填得有多完整。"""
    required = template.required_slots
    optional = template.optional_slots
    if not required and not optional:
        return 1.0
    required_hit = _coverage_score(required, slots)
    if not optional:
        return required_hit
    optional_hit = _coverage_score(optional, slots)
    return clamp_score(0.8 * required_hit + 0.2 * optional_hit)


def structural_alignment_score(
    template: TemplateDefinition,
    slots: dict[str, Any],
) -> float:
    """衡量“抽出来的条件”和“模板能表达的条件”是否同构。

    这里既惩罚 query 里多出的条件，也惩罚模板要求但 query 没给全的关键过滤条件。
    """
    extracted_slots = {
        slot_name
        for slot_name, value in slots.items()
        if value not in (None, "")
    }
    if not extracted_slots:
        return 0.0
    supported_slots = (
        set(template.required_slots)
        | set(template.optional_slots)
        | set(template.slot_constraints)
    )
    if not supported_slots:
        return 0.0

    total_weight = sum(_slot_signal_weight(slot_name) for slot_name in extracted_slots)
    unexpected_slots = extracted_slots - supported_slots
    unexpected_weight = sum(_slot_signal_weight(slot_name) for slot_name in unexpected_slots)
    coverage_score = 1.0 - unexpected_weight / max(1.0, total_weight)

    # 没有过滤条件时，不再强求更复杂的结构完整度。
    extracted_filter_slots = {slot_name for slot_name in extracted_slots if _is_filter_slot(slot_name)}
    if not extracted_filter_slots:
        return clamp_score(coverage_score)

    supported_filter_slots = {slot_name for slot_name in supported_slots if _is_filter_slot(slot_name)}
    matched_filter_weight = sum(
        _slot_signal_weight(slot_name)
        for slot_name in extracted_filter_slots
        if slot_name in supported_filter_slots
    )
    filter_total_weight = sum(_slot_signal_weight(slot_name) for slot_name in extracted_filter_slots)
    filter_score = matched_filter_weight / max(1.0, filter_total_weight)
    required_filter_slots = {
        slot_name
        for slot_name in template.required_slots
        if _is_filter_slot(slot_name)
    }
    if not required_filter_slots:
        return clamp_score(0.55 * coverage_score + 0.45 * filter_score)

    required_filter_weight = sum(_slot_signal_weight(slot_name) for slot_name in required_filter_slots)
    matched_required_filter_weight = sum(
        _slot_signal_weight(slot_name)
        for slot_name in required_filter_slots
        if slot_name in extracted_filter_slots
    )
    completeness_score = matched_required_filter_weight / max(1.0, required_filter_weight)
    return clamp_score(
        0.45 * coverage_score
        + 0.3 * filter_score
        + 0.25 * completeness_score
    )


def constraint_score(
    template: TemplateDefinition,
    text: str,
    slots: dict[str, Any],
) -> float:
    """计算模板自身显式约束是否满足。"""
    lowered = text.lower()
    if has_negative_term(template, lowered):
        return 0.0

    must_score = 1.0
    if template.must_terms:
        matched_groups = 0
        for group in template.must_terms:
            if any(term.lower() in lowered for term in group):
                matched_groups += 1
        must_score = matched_groups / len(template.must_terms)

    slot_constraint_scores: list[float] = []
    for slot_name, allowed_values in template.slot_constraints.items():
        extracted = slots.get(slot_name)
        if extracted in (None, ""):
            if slot_name in template.required_slots:
                slot_constraint_scores.append(0.0)
            continue
        slot_constraint_scores.append(1.0 if _matches_allowed_values(extracted, allowed_values) else 0.0)

    if not slot_constraint_scores:
        return clamp_score(must_score)
    return clamp_score(0.6 * must_score + 0.4 * (sum(slot_constraint_scores) / len(slot_constraint_scores)))


def has_negative_term(template: TemplateDefinition, text: str) -> bool:
    """只要命中模板负向词，就视为该模板不该匹配。"""
    lowered = text.lower()
    return any(term.lower() in lowered for term in template.negative_terms)


def weighted_score(parts: dict[str, float], weights: dict[str, float]) -> float:
    """把各子分按权重线性融合。"""
    total = 0.0
    for name, weight in weights.items():
        total += clamp_score(parts.get(name, 0.0)) * weight
    return clamp_score(total)


def adaptive_score_weights(
    base_weights: dict[str, float],
    slots: dict[str, Any],
) -> dict[str, float]:
    """根据 query 复杂度动态调权。

    过滤条件越多，越要提高结构分和槽位覆盖度的重要性，
    否则多条件 query 很容易被单条件模板抢走。
    """
    weights = {name: float(value) for name, value in base_weights.items()}
    filter_slot_count = sum(1 for slot_name, value in slots.items() if value not in (None, "") and _is_filter_slot(slot_name))
    complexity = min(1.0, filter_slot_count / 3.0)
    if complexity <= 0:
        return _normalize_weights(weights)

    for key in ("lexical", "sample", "vector"):
        if key in weights:
            weights[key] *= 1.0 - (0.15 + (0.05 if key == "vector" else 0.0)) * complexity
    if "slot_fit" in weights:
        weights["slot_fit"] *= 1.0 + 0.2 * complexity
    if "structure" in weights:
        weights["structure"] *= 1.0 + 0.45 * complexity
    if "constraint" in weights:
        weights["constraint"] *= 1.0 + 0.1 * complexity
    if "fusion" in weights:
        weights["fusion"] *= 1.0 + 0.1 * complexity
    return _normalize_weights(weights)


def clamp_score(score: float) -> float:
    """统一把分数限制在 0-1。"""
    if math.isnan(score):
        return 0.0
    return max(0.0, min(1.0, score))


def missing_required_slots(template: TemplateDefinition, slots: dict[str, Any]) -> list[str]:
    """列出当前模板还缺哪些必填槽位。"""
    return [
        slot_name
        for slot_name in template.required_slots
        if slots.get(slot_name) in (None, "")
    ]


def _coverage_score(slot_names: list[str], slots: dict[str, Any]) -> float:
    """简单覆盖率，用于 required/optional 的命中统计。"""
    if not slot_names:
        return 1.0
    hit = sum(1 for slot_name in slot_names if slots.get(slot_name) not in (None, ""))
    return hit / len(slot_names)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _char_ngrams(text: str, size: int) -> list[str]:
    if len(text) < size:
        return [text]
    return [text[idx : idx + size] for idx in range(len(text) - size + 1)]


def _matches_allowed_values(extracted: Any, allowed_values: list[Any]) -> bool:
    """支持标量和字典槽位的宽松值比较。"""
    extracted_candidates = _flatten_value(extracted)
    for allowed in allowed_values:
        allowed_candidates = _flatten_value(allowed)
        if extracted_candidates & allowed_candidates:
            return True
    return False


def _flatten_value(value: Any) -> set[str]:
    if isinstance(value, dict):
        candidates: set[str] = set()
        for key in ("preset", "id", "value", "code"):
            if key in value:
                candidates.add(str(value[key]).lower())
        if not candidates:
            candidates.add(str(value).lower())
        return candidates
    return {str(value).lower()}


def _slot_signal_weight(slot_name: str) -> float:
    """不同槽位对结构判断的价值不同。"""
    if slot_name in LOW_SIGNAL_SLOTS:
        return 0.5
    if slot_name.endswith("_threshold"):
        return 1.5
    if slot_name in FILTER_SLOTS:
        return 1.25
    return 1.0


def _is_filter_slot(slot_name: str) -> bool:
    return slot_name.endswith("_threshold") or slot_name in FILTER_SLOTS


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """把任意权重字典重新归一化。"""
    total = sum(max(0.0, value) for value in weights.values())
    if total <= 0:
        return weights
    return {name: max(0.0, value) / total for name, value in weights.items()}
