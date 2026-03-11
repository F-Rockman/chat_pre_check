from __future__ import annotations

import copy

from template_capability.config import TemplateConfig, load_template_config
from template_capability.extractors import build_slot_registry, normalize_text
from template_capability.fallback import (
    FallbackSuggestion,
    LLMFallbackResolver,
    LLMTemplateSlotResolver,
)
from template_capability.models import (
    MatchResult,
    MatchStatus,
    SlotExtractorDefinition,
    TemplateCandidate,
    TemplateDefinition,
)
from template_capability.scoring import (
    BM25FieldIndex,
    adaptive_score_weights,
    build_utterance_term_sets,
    constraint_score,
    has_negative_term,
    missing_required_slots,
    mixed_terms,
    normalize_candidate_scores,
    reciprocal_rank_fusion,
    sample_similarity_from_terms,
    slot_fit_score,
    structural_alignment_score,
    weighted_score,
)
from template_capability.vector_index import (
    HashingVectorProvider,
    InMemoryVectorIndex,
    VectorSearchBackend,
)


class TemplateCapabilityEngine:
    """面向问数场景的通用模板匹配能力。"""

    def __init__(
        self,
        config: TemplateConfig,
        vector_backend: VectorSearchBackend | None = None,
        llm_fallback_resolver: LLMFallbackResolver | None = None,
        llm_template_slot_resolver: LLMTemplateSlotResolver | None = None,
    ) -> None:
        self.config = config
        self.llm_fallback_resolver = llm_fallback_resolver
        self.llm_template_slot_resolver = llm_template_slot_resolver
        self.slot_registry = build_slot_registry(config.slot_extractors)
        self.templates = {template.template_id: template for template in config.templates}
        self.template_slot_registries = {
            template.template_id: build_slot_registry(self._build_template_slot_definitions(template))
            for template in config.templates
        }
        self.template_documents = {
            template.template_id: self._build_template_document(template)
            for template in config.templates
        }
        self.template_lexical_fields = {
            template.template_id: self._build_template_fields(template)
            for template in config.templates
        }
        self.template_sample_terms = {
            template.template_id: build_utterance_term_sets(template.utterances)
            for template in config.templates
        }
        self.lexical_index = BM25FieldIndex(
            self.template_lexical_fields,
            config.settings.lexical_field_weights,
        )
        self.vector_backend = vector_backend or InMemoryVectorIndex(
            provider=HashingVectorProvider(config.settings.vector_dimension)
        )
        self.vector_backend.build(self.template_documents)

    @classmethod
    def from_file(cls, path: str) -> "TemplateCapabilityEngine":
        return cls(load_template_config(path))

    def match(self, input_text: str) -> MatchResult:
        norm_text = normalize_text(input_text)
        shared_slots = self.slot_registry.extract(norm_text)
        blocked_term = self._match_blocked_term(norm_text)
        if blocked_term is not None:
            return MatchResult(
                template_id=-1,
                status=MatchStatus.UNMATCHED,
                score=0.0,
                query_mode=None,
                slots=shared_slots,
                missing_slots=[],
                trace={
                    "norm_text": norm_text,
                    "blocked_term": blocked_term,
                    "reason": "blocked_intent",
                },
            )
        ranked = self._rank_templates(norm_text)
        top = ranked[0] if ranked else None
        second = ranked[1] if len(ranked) > 1 else None

        if (
            top is None
            or top.score < self.config.settings.match_threshold
            or self._is_ambiguous(top, second)
        ):
            fallback_result = self._resolve_with_fallback(
                input_text=input_text,
                norm_text=norm_text,
                slots=shared_slots,
                ranked=ranked,
                missing_slots=[],
                base_status=MatchStatus.UNMATCHED,
            )
            if fallback_result is not None:
                return fallback_result
            return MatchResult(
                template_id=-1,
                status=MatchStatus.UNMATCHED,
                score=top.score if top is not None else 0.0,
                query_mode=None,
                slots=shared_slots,
                missing_slots=[],
                trace={
                    "norm_text": norm_text,
                    "top_candidates": [candidate.to_dict() for candidate in ranked[:5]],
                    "threshold": self.config.settings.match_threshold,
                    "ambiguity_margin": self.config.settings.ambiguity_margin,
                },
            )

        template = self.templates[top.template_id]
        slots = dict(top.slots)
        missing_slots = missing_required_slots(template, slots)
        status = MatchStatus.MATCHED if not missing_slots else MatchStatus.PARTIAL
        top = self._resolve_template_slots_with_fallback(
            input_text=input_text,
            norm_text=norm_text,
            candidate=top,
            status=status,
        )
        display_candidates = [top] + [
            candidate
            for candidate in ranked
            if candidate.template_id != top.template_id
        ]
        slots = dict(top.slots)
        missing_slots = missing_required_slots(template, slots)
        status = MatchStatus.MATCHED if not missing_slots else MatchStatus.PARTIAL
        if status is MatchStatus.PARTIAL:
            fallback_result = self._resolve_with_fallback(
                input_text=input_text,
                norm_text=norm_text,
                slots=slots or shared_slots,
                ranked=ranked,
                missing_slots=missing_slots,
                base_status=status,
            )
            if fallback_result is not None:
                return fallback_result
        return MatchResult(
            template_id=template.template_id,
            status=status,
            score=top.score,
            query_mode=template.query_mode,
            slots=slots,
            missing_slots=missing_slots,
            metadata=template.metadata,
            trace={
                "norm_text": norm_text,
                "selected_template": top.to_dict(),
                "top_candidates": [candidate.to_dict() for candidate in display_candidates[:5]],
            },
        )

    def route(self, input_text: str) -> MatchResult:
        """兼容旧入口。"""
        return self.match(input_text)

    def _rank_templates(
        self,
        norm_text: str,
    ) -> list[TemplateCandidate]:
        query_term_set = set(mixed_terms(norm_text))
        lexical_recall = self.lexical_index.search(norm_text, self.config.settings.recall_top_k)
        vector_recall = self.vector_backend.search(norm_text, self.config.settings.recall_top_k)
        sample_recall = self._sample_recall(query_term_set)

        lexical_scores = normalize_candidate_scores(lexical_recall)
        vector_scores = normalize_candidate_scores(vector_recall)
        sample_scores = normalize_candidate_scores(sample_recall)
        fusion_scores = reciprocal_rank_fusion(
            [lexical_recall, vector_recall, sample_recall],
            rrf_k=self.config.settings.fusion_rrf_k,
        )
        candidate_ids = set(lexical_scores) | set(vector_scores) | set(sample_scores) | set(fusion_scores)
        ranked: list[TemplateCandidate] = []

        for template_id in candidate_ids:
            slots = self.extract_slots(template_id, norm_text)
            rerank_weights = adaptive_score_weights(self.config.settings.weights, slots)
            ranked.append(
                self._build_candidate(
                    template_id=template_id,
                    norm_text=norm_text,
                    lexical_score=lexical_scores.get(template_id, 0.0),
                    sample_score=sample_scores.get(template_id, 0.0),
                    vector_score=vector_scores.get(template_id, 0.0),
                    fusion_score=fusion_scores.get(template_id, 0.0),
                    slots=slots,
                    weights=rerank_weights,
                )
            )

        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        return ranked

    def _build_template_document(self, template: TemplateDefinition) -> str:
        parts = [template.description, *template.utterances]
        parts.extend(" ".join(group) for group in template.must_terms)
        return normalize_text(" ".join(part for part in parts if part))

    def _build_template_fields(self, template: TemplateDefinition) -> dict[str, list[str]]:
        must_terms_text = " ".join(" ".join(group) for group in template.must_terms)
        return {
            "description": mixed_terms(normalize_text(template.description)),
            "utterances": mixed_terms(normalize_text(" ".join(template.utterances))),
            "must_terms": mixed_terms(normalize_text(must_terms_text)),
        }

    def _sample_recall(self, query_term_set: set[str]) -> list[tuple[str, float]]:
        scored = [
            (
                template_id,
                sample_similarity_from_terms(query_term_set, utterance_term_sets),
            )
            for template_id, utterance_term_sets in self.template_sample_terms.items()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: self.config.settings.recall_top_k]

    def extract_slots(self, template_id: str, text: str) -> dict[str, object]:
        return self.template_slot_registries[template_id].extract(text)

    def _build_template_slot_definitions(
        self,
        template: TemplateDefinition,
    ) -> dict[str, SlotExtractorDefinition]:
        relevant_slots = (
            set(template.required_slots)
            | set(template.optional_slots)
            | set(template.slot_constraints)
            | set(template.slot_extractors)
        )
        merged: dict[str, SlotExtractorDefinition] = {}
        for slot_name in relevant_slots:
            local_definition = template.slot_extractors.get(slot_name)
            if local_definition is not None:
                merged[slot_name] = SlotExtractorDefinition(
                    slot_name=local_definition.slot_name,
                    extractors=[copy.deepcopy(extractor) for extractor in local_definition.extractors],
                )
                continue
            shared_definition = self.config.slot_extractors.get(slot_name)
            if shared_definition is None:
                continue
            merged[slot_name] = SlotExtractorDefinition(
                slot_name=shared_definition.slot_name,
                extractors=[copy.deepcopy(extractor) for extractor in shared_definition.extractors],
            )
        return merged

    def _build_candidate(
        self,
        *,
        template_id: str,
        norm_text: str,
        lexical_score: float,
        sample_score: float,
        vector_score: float,
        fusion_score: float,
        slots: dict[str, object],
        weights: dict[str, float],
    ) -> TemplateCandidate:
        template = self.templates[template_id]
        slot_score = slot_fit_score(template, slots)
        constraint = constraint_score(template, norm_text, slots)
        structure_score = structural_alignment_score(template, slots)
        if has_negative_term(template, norm_text):
            total = 0.0
        else:
            total = weighted_score(
                {
                    "lexical": lexical_score,
                    "sample": sample_score,
                    "vector": vector_score,
                    "fusion": fusion_score,
                    "slot_fit": slot_score,
                    "constraint": constraint,
                    "structure": structure_score,
                },
                weights,
            )
        return TemplateCandidate(
            template_id=template.template_id,
            query_mode=template.query_mode,
            score=total,
            lexical_score=lexical_score,
            sample_score=sample_score,
            vector_score=vector_score,
            fusion_score=fusion_score,
            slot_fit_score=slot_score,
            constraint_score=constraint,
            structure_score=structure_score,
            slots=dict(slots),
            missing_slots=missing_required_slots(template, slots),
            trace={},
            metadata=template.metadata,
        )

    def _is_ambiguous(
        self,
        top: TemplateCandidate,
        second: TemplateCandidate | None,
    ) -> bool:
        if second is None:
            return False
        if second.score < self.config.settings.match_threshold:
            return False
        return (top.score - second.score) < self.config.settings.ambiguity_margin

    def _match_blocked_term(self, norm_text: str) -> str | None:
        for term in self.config.settings.blocked_terms:
            lowered = term.lower()
            if lowered and lowered in norm_text:
                return term
        return None

    def _resolve_template_slots_with_fallback(
        self,
        *,
        input_text: str,
        norm_text: str,
        candidate: TemplateCandidate,
        status: MatchStatus,
    ) -> TemplateCandidate:
        template = self.templates[candidate.template_id]
        missing_slots = missing_required_slots(template, candidate.slots)
        if not self._should_use_template_slot_fallback(candidate, missing_slots, status):
            return candidate
        if self.llm_template_slot_resolver is None:
            return candidate
        suggestion = self.llm_template_slot_resolver.resolve_slots(
            input_text=input_text,
            normalized_text=norm_text,
            template=template,
            current_slots=dict(candidate.slots),
            missing_slots=missing_slots,
        )
        if suggestion is None or not suggestion.slots:
            return candidate
        merged_slots = dict(candidate.slots)
        merged_slots.update(suggestion.slots)
        rerank_weights = adaptive_score_weights(self.config.settings.weights, merged_slots)
        enriched = self._build_candidate(
            template_id=candidate.template_id,
            norm_text=norm_text,
            lexical_score=candidate.lexical_score,
            sample_score=candidate.sample_score,
            vector_score=candidate.vector_score,
            fusion_score=candidate.fusion_score,
            slots=merged_slots,
            weights=rerank_weights,
        )
        return TemplateCandidate(
            template_id=enriched.template_id,
            query_mode=enriched.query_mode,
            score=enriched.score,
            lexical_score=enriched.lexical_score,
            sample_score=enriched.sample_score,
            vector_score=enriched.vector_score,
            fusion_score=enriched.fusion_score,
            slot_fit_score=enriched.slot_fit_score,
            constraint_score=enriched.constraint_score,
            structure_score=enriched.structure_score,
            slots=enriched.slots,
            missing_slots=enriched.missing_slots,
            trace={
                **enriched.trace,
                "slot_fallback_used": True,
                "slot_fallback_trace": suggestion.trace,
            },
            metadata=enriched.metadata,
        )

    def _should_use_template_slot_fallback(
        self,
        candidate: TemplateCandidate,
        missing_slots: list[str],
        status: MatchStatus,
    ) -> bool:
        if not self.config.settings.llm_slot_fallback_enabled:
            return False
        template = self.templates[candidate.template_id]
        template_settings = template.llm_slot_extraction
        if not template_settings.get("enabled", False):
            return False
        if candidate.score < self.config.settings.llm_slot_fallback_min_score:
            return False
        if status is MatchStatus.MATCHED:
            return bool(
                self.config.settings.llm_slot_fallback_allow_on_matched
                or template_settings.get("allow_on_matched", False)
            )
        if status is not MatchStatus.PARTIAL:
            return False
        return len(missing_slots) <= self.config.settings.llm_slot_fallback_max_missing_slots

    def _resolve_with_fallback(
        self,
        *,
        input_text: str,
        norm_text: str,
        slots: dict[str, object],
        ranked: list[TemplateCandidate],
        missing_slots: list[str],
        base_status: MatchStatus,
    ) -> MatchResult | None:
        if not self._should_use_fallback(ranked, missing_slots, base_status):
            return None
        if self.llm_fallback_resolver is None:
            return None
        suggestion = self.llm_fallback_resolver.resolve(
            input_text=input_text,
            normalized_text=norm_text,
            slots=dict(slots),
            candidates=ranked[: self.config.settings.llm_fallback_max_candidates],
            templates=self.templates,
        )
        if suggestion is None:
            return None
        return self._build_fallback_result(norm_text, ranked, suggestion)

    def _should_use_fallback(
        self,
        ranked: list[TemplateCandidate],
        missing_slots: list[str],
        base_status: MatchStatus,
    ) -> bool:
        if not self.config.settings.llm_fallback_enabled:
            return False
        top = ranked[0] if ranked else None
        if base_status is MatchStatus.PARTIAL:
            return len(missing_slots) <= self.config.settings.llm_fallback_max_missing_slots
        if top is None:
            return False
        lower_bound = self.config.settings.match_threshold - self.config.settings.llm_fallback_score_margin
        return top.score >= max(0.0, lower_bound)

    def _build_fallback_result(
        self,
        norm_text: str,
        ranked: list[TemplateCandidate],
        suggestion: FallbackSuggestion,
    ) -> MatchResult:
        return MatchResult(
            template_id=suggestion.template_id,
            status=suggestion.status,
            score=suggestion.score,
            query_mode=suggestion.query_mode,
            slots=suggestion.slots,
            missing_slots=suggestion.missing_slots,
            metadata=suggestion.metadata,
            trace={
                "norm_text": norm_text,
                "fallback_used": True,
                "fallback_trace": suggestion.trace,
                "top_candidates": [candidate.to_dict() for candidate in ranked[:5]],
            },
        )
