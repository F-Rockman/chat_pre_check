from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from template_capability.models import MatchStatus, TemplateCandidate, TemplateDefinition


@dataclass(slots=True)
class FallbackSuggestion:
    template_id: str | int
    status: MatchStatus
    score: float
    query_mode: str | None
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


class LLMFallbackResolver(Protocol):
    def resolve(
        self,
        *,
        input_text: str,
        normalized_text: str,
        slots: dict[str, Any],
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
    ) -> FallbackSuggestion | None:
        ...
