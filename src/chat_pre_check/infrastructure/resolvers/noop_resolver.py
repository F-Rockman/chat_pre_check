from __future__ import annotations

from typing import Iterable

from chat_pre_check.domain.models import Candidate


class NoopResolver:
    """空解析器：离线模式或降级场景下返回预置候选。"""

    def __init__(self, candidates: Iterable[Candidate] | None = None) -> None:
        self._candidates = list(candidates or [])

    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        return self._candidates[:topk]
