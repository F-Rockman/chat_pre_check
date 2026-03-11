from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# 这一层默认权重只定义“没有显式配置时系统怎么工作”，
# 真正生效的值仍然优先来自 templates.json 里的 matcher 配置。
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
    """模板匹配只区分命中、部分命中、未命中。

    这是整个能力层最外层的状态枚举：
    - MATCHED: 模板已确定，且必填槽位齐全
    - PARTIAL: 模板已基本确定，但仍缺少关键槽位
    - UNMATCHED: 没有稳定命中的模板，外部应按 -1 理解
    """

    MATCHED = "matched"
    PARTIAL = "partial"
    UNMATCHED = "unmatched"


@dataclass(slots=True)
class MatcherSettings:
    """匹配引擎运行参数。

    这类字段不描述任何具体模板，只描述“所有模板共用的匹配策略”。
    阅读顺序建议按下面三组理解：
    1. 召回与阈值: `match_threshold` / `ambiguity_margin` / `recall_top_k`
    2. 打分融合: `weights` / `lexical_field_weights` / `fusion_rrf_k`
    3. 兜底策略: `blocked_terms` / `llm_fallback_*` / `llm_slot_fallback_*`
    """

    # 最终 top1 低于该阈值时，直接视为未命中。
    match_threshold: float
    # top1 和 top2 同时够高但差距过小时，判为歧义，返回 -1 或交给 fallback。
    ambiguity_margin: float
    # 每条召回链各自保留多少候选进入后续融合。
    recall_top_k: int
    # 最终总分的线性融合权重，key 对应 scoring.py 里的子分名。
    weights: dict[str, float]
    # BM25F 的字段权重，通常 must_terms > utterances > description。
    lexical_field_weights: dict[str, float] = field(default_factory=dict)
    # Reciprocal Rank Fusion 的平滑参数，值越大，不同召回路的 rank 差异越不敏感。
    fusion_rrf_k: int = 60
    # 向量召回约定的 embedding 维度，便于外部向量服务接入时保持一致。
    vector_dimension: int = 512
    # 全局负向意图词，命中后直接短路为 UNMATCHED。
    blocked_terms: list[str] = field(default_factory=list)
    # 模板选择级 LLM fallback，总开关。
    llm_fallback_enabled: bool = False
    # 模板选择级 fallback 最多看多少个 top 候选。
    llm_fallback_max_candidates: int = 3
    # top1 距离主阈值多近时，允许 unmatched case 进入 fallback。
    llm_fallback_score_margin: float = 0.08
    # partial case 最多缺多少必填槽位时，允许进入模板选择级 fallback。
    llm_fallback_max_missing_slots: int = 2
    # 模板级 LLM 补参，总开关。它只在模板已基本命中后触发。
    llm_slot_fallback_enabled: bool = False
    # 模板级补参最多允许补几个缺失槽位。
    llm_slot_fallback_max_missing_slots: int = 2
    # 候选模板至少达到该分数，才值得付一次模板级 LLM 成本。
    llm_slot_fallback_min_score: float = 0.58
    # 是否允许对已经 MATCHED 的模板也尝试再补充可选槽位。
    llm_slot_fallback_allow_on_matched: bool = False

    def __post_init__(self) -> None:
        # 兼容直接手写 MatcherSettings 的场景；未传权重时补默认值。
        if not self.weights:
            self.weights = dict(DEFAULT_SCORE_WEIGHTS)
        if not self.lexical_field_weights:
            self.lexical_field_weights = dict(DEFAULT_LEXICAL_FIELD_WEIGHTS)


@dataclass(slots=True)
class SlotExtractorDefinition:
    """配置驱动的槽位抽取定义。

    它描述的是“某一个槽位可以怎样被抽出来”，而不是模板本身。
    同一个 `slot_name` 在不同模板里可以复用，也可以被模板本地覆写。
    """

    slot_name: str
    # extractor 按顺序尝试，先命中的规则优先级更高。
    extractors: list[dict[str, Any]]


@dataclass(slots=True)
class TemplateDefinition:
    """只面向问数场景的模板定义。

    这是系统里最重要的静态配置对象。一个模板同时承担三类职责：
    1. 说明“这类 query 想问什么”      -> `description` / `utterances`
    2. 说明“成立至少需要什么条件”    -> `required_slots` / `must_terms`
    3. 说明“参数应该怎么抽、怎么约束” -> `slot_extractors` / `slot_constraints`
    """

    # 模板唯一标识，也是最终返回给外部系统的主键。
    template_id: str
    # 模板结果类型，例如 count / topn / list；它是问法产物，不是召回条件。
    query_mode: str
    # 供开发和召回理解使用的简短说明，适合写“这个模板到底问什么”。
    description: str
    # 模板的代表性问法样例，主要用于 lexical/sample 召回。
    utterances: list[str]
    # 没有这些槽位时，模板最多只能是 PARTIAL，不能是 MATCHED。
    required_slots: list[str]
    # 这些槽位会提升模板完整度，但缺失时不阻止命中。
    optional_slots: list[str]
    # 必须命中的词组列表；每组内是近义词关系，组与组之间是“都要满足”。
    must_terms: list[list[str]]
    # 负向排斥词，只要命中就明确说明“不该走这个模板”。
    negative_terms: list[str]
    # 对抽取值的显式限制，例如某个槽位只能是特定枚举值。
    slot_constraints: dict[str, list[Any]]
    # 模板自己的槽位抽取器。它优先于根级共享定义。
    slot_extractors: dict[str, "SlotExtractorDefinition"] = field(default_factory=dict)
    # 模板级 LLM 补参配置，只在模板已基本命中后才会使用。
    llm_slot_extraction: dict[str, Any] = field(default_factory=dict)
    # 业务附加信息，原样透传到匹配结果里，不参与排序。
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TemplateCandidate:
    """单个模板候选的打分轨迹。

    这是纯运行期对象，只存在于一次 match 过程中。
    它回答的是：“当前 query 下，这个模板为什么排在这个位置？”
    """

    template_id: str
    query_mode: str
    # 融合后的最终分，用来和其他模板排序。
    score: float
    # 下面这些都是组成 `score` 的子分，便于调试和调参。
    lexical_score: float
    sample_score: float
    vector_score: float
    fusion_score: float
    slot_fit_score: float
    constraint_score: float
    structure_score: float
    # 这是“按该模板自己的 extractor”抽出来的槽位，不是全局抽参结果。
    slots: dict[str, Any]
    # 当前模板如果想成为 MATCHED，还缺哪些 required_slots。
    missing_slots: list[str]
    # 预留给更细的诊断轨迹，例如 LLM 补参耗时、重排原因。
    trace: dict[str, Any] = field(default_factory=dict)
    # 透传模板的 metadata，方便候选调试时直接看到业务标签。
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # trace 输出统一走 dict，方便 CLI、测试和报告直接序列化。
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
            "slots": self.slots,
            "missing_slots": self.missing_slots,
            "trace": self.trace,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class MatchResult:
    """模板匹配输出。

    这是能力层对外的最终契约。外部通常只需要关心三件事：
    1. `template_id` 是哪个；未命中时固定为 `-1`
    2. `status` 是 matched / partial / unmatched
    3. `slots` 和 `missing_slots` 说明参数是否齐全
    """

    # 命中时是模板 id，未命中时固定返回 -1。
    template_id: str | int
    status: MatchStatus
    # 这里是最终对外分数，已经是融合后的 top1 分。
    score: float
    # 模板声明的查询模式；未命中时为 None。
    query_mode: str | None
    # 最终确认可用的槽位集合。
    slots: dict[str, Any] = field(default_factory=dict)
    # 对 partial 场景尤其关键，告诉外部还差哪些必要参数。
    missing_slots: list[str] = field(default_factory=list)
    # 透传模板 metadata，供业务侧做后续路由或展示。
    metadata: dict[str, Any] = field(default_factory=dict)
    # 调试轨迹，不应被业务逻辑强依赖。
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
