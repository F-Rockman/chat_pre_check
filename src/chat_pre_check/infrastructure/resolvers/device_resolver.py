from __future__ import annotations

from typing import Any

from chat_pre_check.domain.models import Candidate


class DeviceResolver:
    def __init__(self, client: Any, index_name: str) -> None:
        self.client = client
        self.index_name = index_name

    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        hits = self.client.text_search(
            index_name=self.index_name,
            text=text,
            topk=topk,
            fields=["name^3", "ip^4", "aliases"],
        )
        return self._to_candidates(hits)

    @staticmethod
    def _to_candidates(hits: list[dict]) -> list[Candidate]:
        if not hits:
            return []
        max_score = max(hit.get("_score", 1.0) for hit in hits) or 1.0
        candidates: list[Candidate] = []
        for hit in hits:
            source = hit.get("_source", {})
            score = hit.get("_score", 0.0) / max_score
            candidates.append(
                Candidate(
                    entity_id=str(source.get("id", hit.get("_id"))),
                    name=str(source.get("name", source.get("ip", hit.get("_id")))),
                    score=float(score),
                    meta=source.get("metadata", {}),
                )
            )
        return candidates
