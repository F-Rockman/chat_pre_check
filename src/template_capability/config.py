from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from template_capability.models import (
    MatcherSettings,
    SlotExtractorDefinition,
    TemplateDefinition,
)


@dataclass(slots=True)
class TemplateConfig:
    """模板能力完整配置。"""

    settings: MatcherSettings
    slot_extractors: dict[str, SlotExtractorDefinition]
    templates: list[TemplateDefinition]


def load_template_config(path: str | Path) -> TemplateConfig:
    """从 JSON 文件加载配置。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    matcher_payload = payload.get("matcher", {})
    vector_payload = matcher_payload.get("vector", {})
    fallback_payload = matcher_payload.get("llm_fallback", {})
    settings = MatcherSettings(
        match_threshold=float(matcher_payload.get("match_threshold", 0.58)),
        ambiguity_margin=float(matcher_payload.get("ambiguity_margin", 0.03)),
        recall_top_k=int(matcher_payload.get("recall_top_k", 30)),
        weights={
            str(key): float(value)
            for key, value in matcher_payload.get("weights", {}).items()
        }
        or {
            "lexical": 0.45,
            "vector": 0.25,
            "slot_fit": 0.2,
            "constraint": 0.1,
        },
        vector_dimension=int(vector_payload.get("dimension", 512)),
        blocked_terms=[str(term) for term in matcher_payload.get("blocked_terms", [])],
        llm_fallback_enabled=bool(fallback_payload.get("enabled", False)),
        llm_fallback_max_candidates=int(fallback_payload.get("max_candidates", 3)),
        llm_fallback_score_margin=float(fallback_payload.get("score_margin", 0.08)),
        llm_fallback_max_missing_slots=int(fallback_payload.get("max_missing_slots", 2)),
    )

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
            metadata=dict(item.get("metadata", {})),
        )
        for item in payload.get("templates", [])
        if isinstance(item, dict)
    ]
    return TemplateConfig(
        settings=settings,
        slot_extractors=slot_extractors,
        templates=templates,
    )


def _normalize_constraint_values(values: Any) -> list[Any]:
    if isinstance(values, list):
        return values
    return [values]
