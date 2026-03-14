from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from template_capability.models import (
    DEFAULT_LEXICAL_FIELD_WEIGHTS,
    DEFAULT_SCORE_WEIGHTS,
    MatcherSettings,
    QueryRewriteRule,
    QueryRewriteSettings,
    SlotExtractorDefinition,
    TemplateDefinition,
)


@dataclass(slots=True)
class TemplateConfig:
    """模板能力完整配置。

    这是配置文件加载后的根对象，按职责拆成三块：
    - `settings`: 全局匹配策略
    - `slot_extractors`: 根级共享槽位定义
    - `templates`: 具体模板列表
    """

    settings: MatcherSettings
    query_rewrite: QueryRewriteSettings = field(default_factory=QueryRewriteSettings)
    slot_extractors: dict[str, SlotExtractorDefinition] = field(default_factory=dict)
    templates: list[TemplateDefinition] = field(default_factory=list)


def load_template_config(path: str | Path) -> TemplateConfig:
    """从 JSON 文件加载配置。"""
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    matcher_payload = payload.get("matcher", {})
    rewrite_payload = payload.get("query_rewrite", {})
    vector_payload = matcher_payload.get("vector", {})
    fallback_payload = matcher_payload.get("llm_fallback", {})
    slot_fallback_payload = matcher_payload.get("llm_slot_fallback", {})
    settings = MatcherSettings(
        match_threshold=float(matcher_payload.get("match_threshold", 0.58)),
        ambiguity_margin=float(matcher_payload.get("ambiguity_margin", 0.03)),
        recall_top_k=int(matcher_payload.get("recall_top_k", 30)),
        weights={
            str(key): float(value)
            for key, value in matcher_payload.get("weights", {}).items()
        }
        or dict(DEFAULT_SCORE_WEIGHTS),
        lexical_field_weights={
            str(key): float(value)
            for key, value in matcher_payload.get("lexical_field_weights", {}).items()
        }
        or dict(DEFAULT_LEXICAL_FIELD_WEIGHTS),
        fusion_rrf_k=int(matcher_payload.get("fusion_rrf_k", 60)),
        vector_dimension=int(vector_payload.get("dimension", 512)),
        blocked_terms=[str(term) for term in matcher_payload.get("blocked_terms", [])],
        llm_fallback_enabled=bool(fallback_payload.get("enabled", False)),
        llm_fallback_max_candidates=int(fallback_payload.get("max_candidates", 3)),
        llm_fallback_score_margin=float(fallback_payload.get("score_margin", 0.08)),
        llm_fallback_max_missing_slots=int(fallback_payload.get("max_missing_slots", 2)),
        llm_slot_fallback_enabled=bool(slot_fallback_payload.get("enabled", False)),
        llm_slot_fallback_max_missing_slots=int(slot_fallback_payload.get("max_missing_slots", 2)),
        llm_slot_fallback_min_score=float(slot_fallback_payload.get("min_score", matcher_payload.get("match_threshold", 0.58))),
        llm_slot_fallback_allow_on_matched=bool(slot_fallback_payload.get("allow_on_matched", False)),
    )

    query_rewrite = QueryRewriteSettings(
        enabled=bool(rewrite_payload.get("enabled", False)),
        max_passes=max(1, int(rewrite_payload.get("max_passes", 1))),
        dictionary_path=_resolve_dictionary_path(
            rewrite_payload.get("dictionary_path"),
            base_dir=config_path.parent,
        ),
        reload_on_change=bool(rewrite_payload.get("reload_on_change", True)),
        rules=[
            rule
            for index, item in enumerate(rewrite_payload.get("rules", []), start=1)
            if isinstance(item, dict)
            for rule in [_build_query_rewrite_rule(item, index)]
            if rule is not None
        ],
    )

    # 根级 slot_extractors 是共享定义，只在模板本地未覆写时才会生效。
    slot_extractors = {
        str(slot_name): SlotExtractorDefinition(
            slot_name=str(slot_name),
            extractors=[
                dict(extractor)
                for extractor in definition.get("extractors", [])
                if isinstance(extractor, dict)
            ],
        )
        for slot_name, definition in payload.get("slot_extractors", {}).items()
        if isinstance(definition, dict)
    }

    # templates 是实际参与召回和匹配的对象；每条模板都会被标准化成强类型 dataclass。
    templates = [
        TemplateDefinition(
            template_id=str(item["template_id"]),
            query_mode=str(item.get("query_mode", "metric_query")),
            description=str(item.get("description", "")),
            utterances=[str(text) for text in item.get("utterances", [])],
            required_slots=[str(slot) for slot in item.get("required_slots", [])],
            optional_slots=[str(slot) for slot in item.get("optional_slots", [])],
            must_terms=[
                [str(term) for term in group]
                for group in item.get("must_terms", [])
                if isinstance(group, list) and group
            ],
            negative_terms=[str(term) for term in item.get("negative_terms", [])],
            slot_constraints={
                str(slot_name): _normalize_constraint_values(values)
                for slot_name, values in item.get("slot_constraints", {}).items()
            },
            slot_extractors={
                str(slot_name): SlotExtractorDefinition(
                    slot_name=str(slot_name),
                    extractors=[
                        dict(extractor)
                        for extractor in definition.get("extractors", [])
                        if isinstance(extractor, dict)
                    ],
                )
                for slot_name, definition in item.get("slot_extractors", {}).items()
                if isinstance(definition, dict)
            },
            llm_slot_extraction=dict(item.get("llm_slot_extraction", {})),
            metadata=dict(item.get("metadata", {})),
        )
        for item in payload.get("templates", [])
        if isinstance(item, dict)
    ]
    return TemplateConfig(
        settings=settings,
        query_rewrite=query_rewrite,
        slot_extractors=slot_extractors,
        templates=templates,
    )


def _normalize_constraint_values(values: Any) -> list[Any]:
    # 配置层允许单值或列表写法，运行时统一转成列表，简化后续判断逻辑。
    if isinstance(values, list):
        return values
    return [values]


def _build_query_rewrite_rule(item: dict[str, Any], index: int) -> QueryRewriteRule | None:
    source = str(item.get("source", "")).strip()
    target = str(item.get("target", "")).strip()
    if not source or not target:
        return None
    return QueryRewriteRule(
        source=source,
        target=target,
        rule_id=str(item.get("rule_id", f"rewrite_rule_{index}")),
        match_mode=str(item.get("match_mode", "substring") or "substring"),
    )


def _resolve_dictionary_path(raw_path: Any, *, base_dir: Path) -> str | None:
    if raw_path in (None, ""):
        return None
    candidate = Path(str(raw_path))
    if not candidate.is_absolute():
        primary = (base_dir / candidate).resolve()
        fallback = (Path.cwd() / candidate).resolve()
        candidate = primary if primary.exists() or not fallback.exists() else fallback
    return str(candidate)
