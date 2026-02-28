from __future__ import annotations

from typing import Iterable

from chat_pre_check.domain.models import Candidate


class NoopResolver:
    def __init__(self, candidates: Iterable[Candidate] | None = None) -> None:
        self._candidates = list(candidates or [])

    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        return self._candidates[:topk]
