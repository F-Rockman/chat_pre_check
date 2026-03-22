from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from template_capability.models import TemplateCandidate, TemplateDefinition
from template_capability.openai_client import (
    build_openai_client,
    extract_chat_completion_content,
    parse_json_content,
)
from template_capability.scoring import clamp_score, mixed_terms


@dataclass(slots=True)
class RerankScore:
    """单个模板的 rerank 结果。"""

    score: float
    trace: dict[str, Any] = field(default_factory=dict)


class TemplateReranker(Protocol):
    """二阶段模板精排接口。"""

    def rerank(
        self,
        *,
        normalized_text: str,
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
        template_documents: dict[str, str],
    ) -> dict[str, RerankScore]:
        ...


class NoopTemplateReranker:
    """默认空实现，保证老配置完全不受影响。"""

    def rerank(
        self,
        *,
        normalized_text: str,
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
        template_documents: dict[str, str],
    ) -> dict[str, RerankScore]:
        return {}


class TermOverlapTemplateReranker:
    """一个轻量本地 reranker。

    它不是 learned cross-encoder，只是把 query 和模板文档的词面覆盖度
    再算一遍，并额外看 must_terms 是否被 query 触发，适合本地调试和离线回归。
    """

    def rerank(
        self,
        *,
        normalized_text: str,
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
        template_documents: dict[str, str],
    ) -> dict[str, RerankScore]:
        query_terms = set(mixed_terms(normalized_text))
        if not query_terms:
            return {}
        scores: dict[str, RerankScore] = {}
        for candidate in candidates:
            template = templates[candidate.template_id]
            document_terms = set(mixed_terms(template_documents.get(candidate.template_id, "")))
            overlap_score = len(query_terms & document_terms) / max(1, len(query_terms))
            must_group_hit_rate = _must_group_hit_rate(normalized_text, template)
            score = clamp_score(0.7 * overlap_score + 0.3 * must_group_hit_rate)
            scores[candidate.template_id] = RerankScore(
                score=score,
                trace={
                    "provider": "term_overlap",
                    "overlap_score": round(overlap_score, 6),
                    "must_group_hit_rate": round(must_group_hit_rate, 6),
                },
            )
        return scores


@dataclass(slots=True)
class OpenAICompatibleTemplateReranker:
    """基于 OpenAI-compatible 协议的 listwise reranker。

    它更像一个“远端判别器”而不是真正的 cross-encoder：
    - 优点是可以直接接现有 Qwen / GLM / 内部兼容网关
    - 缺点是时延和成本高于本地轻量 reranker
    """

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 8.0
    client: Any | None = field(default=None, repr=False, compare=False)

    def rerank(
        self,
        *,
        normalized_text: str,
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
        template_documents: dict[str, str],
    ) -> dict[str, RerankScore]:
        if not candidates:
            return {}
        start = time.perf_counter()
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You rerank candidate templates for a deterministic metric-query matcher. "
                        "Return a strict JSON object with a single key named scores. "
                        "Each scores value must map template_id to a float between 0 and 1."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_prompt(
                        normalized_text=normalized_text,
                        candidates=candidates,
                        templates=templates,
                        template_documents=template_documents,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        raw = self._post_json(payload)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if raw is None:
            return {}
        return self._coerce_scores(raw, elapsed_ms=elapsed_ms, candidate_ids=[item.template_id for item in candidates])

    def _build_prompt(
        self,
        *,
        normalized_text: str,
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
        template_documents: dict[str, str],
    ) -> str:
        candidate_payload = []
        for candidate in candidates:
            template = templates[candidate.template_id]
            candidate_payload.append(
                {
                    "template_id": candidate.template_id,
                    "description": template.description,
                    "utterances": template.utterances[:5],
                    "required_slots": template.required_slots,
                    "required_one_of": [group.to_dict() for group in template.required_one_of],
                    "conditional_required": [rule.to_dict() for rule in template.conditional_required],
                    "must_terms": [[rule.term for rule in group] for group in template.must_terms],
                    "slot_constraints": template.slot_constraints,
                    "document": template_documents.get(candidate.template_id, ""),
                    "current_slots": candidate.slots,
                    "missing_slots": candidate.missing_slots,
                    "base_score": round(candidate.score, 6),
                }
            )
        return (
            f"query: {normalized_text}\n"
            f"candidates: {json.dumps(candidate_payload, ensure_ascii=False)}\n"
            "Score each template by semantic fit, filter completeness, and whether the template structure can truly support the query. "
            "Prefer templates that explain more query constraints. "
            "Return only JSON like {\"scores\": {\"template.id\": 0.93}}."
        )

    def _coerce_scores(
        self,
        payload: dict[str, Any],
        *,
        elapsed_ms: float,
        candidate_ids: list[str],
    ) -> dict[str, RerankScore]:
        raw_scores = payload.get("scores")
        if not isinstance(raw_scores, dict):
            return {}
        allowed_ids = set(candidate_ids)
        scores: dict[str, RerankScore] = {}
        for template_id, raw_value in raw_scores.items():
            template_id = str(template_id).strip()
            if template_id not in allowed_ids:
                continue
            try:
                value = clamp_score(float(raw_value))
            except (TypeError, ValueError):
                continue
            scores[template_id] = RerankScore(
                score=value,
                trace={
                    "provider": "openai_compatible",
                    "model": self.model,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )
        return scores

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            client = self.client or build_openai_client(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
            )
            response = client.chat.completions.create(**payload)
        except Exception:
            return None
        return parse_json_content(extract_chat_completion_content(response))


def _must_group_hit_rate(normalized_text: str, template: TemplateDefinition) -> float:
    groups = template.must_terms
    if not groups:
        return 1.0
    hits = 0
    for group in groups:
        if any(rule.term and rule.term in normalized_text for rule in group):
            hits += 1
    return hits / len(groups)


def resolve_reranker_api_key(options: dict[str, Any]) -> str:
    """统一解析 reranker 所需的 API Key。"""
    api_key = str(options.get("api_key", "")).strip()
    if api_key:
        return api_key
    api_key_env = str(options.get("api_key_env", "")).strip()
    if api_key_env:
        return os.environ.get(api_key_env, "").strip()
    return ""
