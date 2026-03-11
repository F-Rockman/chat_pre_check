from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from template_capability.models import TemplateDefinition


TOKEN_RE = re.compile(r"[a-z0-9_.-]+|[\u4e00-\u9fff]+")


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
    if not utterances:
        return 0.0
    query_terms = set(mixed_terms(text))
    if not query_terms:
        return 0.0
    best = 0.0
    for utterance in utterances:
        utterance_terms = set(mixed_terms(utterance))
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


def normalize_candidate_scores(items: list[tuple[str, float]]) -> dict[str, float]:
    if not items:
        return {}
    top_score = max(score for _, score in items)
    if top_score <= 0:
        return {doc_id: 0.0 for doc_id, _ in items}
    return {doc_id: clamp_score(score / top_score) for doc_id, score in items}


def slot_fit_score(template: TemplateDefinition, slots: dict[str, Any]) -> float:
    required = template.required_slots
    optional = template.optional_slots
    if not required and not optional:
        return 1.0
    required_hit = _coverage_score(required, slots)
    if not optional:
        return required_hit
    optional_hit = _coverage_score(optional, slots)
    return clamp_score(0.8 * required_hit + 0.2 * optional_hit)


def constraint_score(
    template: TemplateDefinition,
    text: str,
    slots: dict[str, Any],
) -> float:
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
    lowered = text.lower()
    return any(term.lower() in lowered for term in template.negative_terms)


def weighted_score(parts: dict[str, float], weights: dict[str, float]) -> float:
    total = 0.0
    for name, weight in weights.items():
        total += clamp_score(parts.get(name, 0.0)) * weight
    return clamp_score(total)


def clamp_score(score: float) -> float:
    if math.isnan(score):
        return 0.0
    return max(0.0, min(1.0, score))


def missing_required_slots(template: TemplateDefinition, slots: dict[str, Any]) -> list[str]:
    return [
        slot_name
        for slot_name in template.required_slots
        if slots.get(slot_name) in (None, "")
    ]


def _coverage_score(slot_names: list[str], slots: dict[str, Any]) -> float:
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
