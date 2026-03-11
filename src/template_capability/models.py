from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "lexical": 0.2,
    "sample": 0.1,
    "vector": 0.15,
    "fusion": 0.1,
    "slot_fit": 0.15,
    "constraint": 0.1,
    "structure": 0.2,
}

DEFAULT_LEXICAL_FIELD_WEIGHTS: dict[str, float] = {
    "description": 0.6,
    "utterances": 1.0,
    "must_terms": 1.6,
}


class MatchStatus(str, Enum):
    """模板匹配只区分命中、部分命中、未命中。"""

    MATCHED = "matched"
    PARTIAL = "partial"
    UNMATCHED = "unmatched"


@dataclass(slots=True)
class MatcherSettings:
    """匹配引擎运行参数。"""

    match_threshold: float
    ambiguity_margin: float
    recall_top_k: int
    weights: dict[str, float]
    lexical_field_weights: dict[str, float] = field(default_factory=dict)
    fusion_rrf_k: int = 60
    vector_dimension: int = 512
    blocked_terms: list[str] = field(default_factory=list)
    llm_fallback_enabled: bool = False
    llm_fallback_max_candidates: int = 3
    llm_fallback_score_margin: float = 0.08
    llm_fallback_max_missing_slots: int = 2

    def __post_init__(self) -> None:
        if not self.weights:
            self.weights = dict(DEFAULT_SCORE_WEIGHTS)
        if not self.lexical_field_weights:
            self.lexical_field_weights = dict(DEFAULT_LEXICAL_FIELD_WEIGHTS)


@dataclass(slots=True)
class SlotExtractorDefinition:
    """配置驱动的槽位抽取定义。"""

    slot_name: str
    extractors: list[dict[str, Any]]


@dataclass(slots=True)
class TemplateDefinition:
    """只面向问数场景的模板定义。"""

    template_id: str
    query_mode: str
    description: str
    utterances: list[str]
    required_slots: list[str]
    optional_slots: list[str]
    must_terms: list[list[str]]
    negative_terms: list[str]
    slot_constraints: dict[str, list[Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TemplateCandidate:
    """单个模板候选的打分轨迹。"""

    template_id: str
    query_mode: str
    score: float
    lexical_score: float
    sample_score: float
    vector_score: float
    fusion_score: float
    slot_fit_score: float
    constraint_score: float
    structure_score: float
    missing_slots: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "query_mode": self.query_mode,
            "score": self.score,
            "lexical_score": self.lexical_score,
            "sample_score": self.sample_score,
            "vector_score": self.vector_score,
            "fusion_score": self.fusion_score,
            "slot_fit_score": self.slot_fit_score,
            "constraint_score": self.constraint_score,
            "structure_score": self.structure_score,
            "missing_slots": self.missing_slots,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class MatchResult:
    """模板匹配输出。"""

    template_id: str | int
    status: MatchStatus
    score: float
    query_mode: str | None
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "status": self.status.value,
            "score": self.score,
            "query_mode": self.query_mode,
            "slots": self.slots,
            "missing_slots": self.missing_slots,
            "metadata": self.metadata,
            "trace": self.trace,
        }
