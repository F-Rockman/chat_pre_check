from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Protocol

from template_capability.scoring import mixed_terms


class VectorProvider(Protocol):
    dimension: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class VectorSearchBackend(Protocol):
    def build(self, documents: dict[str, str]) -> None:
        ...

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        ...


@dataclass(slots=True)
class HashingVectorProvider:
    """本地默认向量提供器，接口和外部 512 维实现保持一致。"""

    dimension: int = 512

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for term in mixed_terms(text):
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


@dataclass(slots=True)
class InMemoryVectorIndex:
    """可替换的本地向量检索后端。"""

    provider: VectorProvider
    vectors: dict[str, list[float]] = field(default_factory=dict)

    def build(self, documents: dict[str, str]) -> None:
        doc_ids = list(documents.keys())
        embeddings = self.provider.embed_texts([documents[doc_id] for doc_id in doc_ids])
        self.vectors = {
            doc_id: embedding
            for doc_id, embedding in zip(doc_ids, embeddings, strict=True)
        }

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        if not self.vectors:
            return []
        query_vector = self.provider.embed_texts([query_text])[0]
        results = [
            (doc_id, _cosine_similarity(query_vector, vector))
            for doc_id, vector in self.vectors.items()
        ]
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:top_k]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    total = sum(lv * rv for lv, rv in zip(left, right, strict=True))
    return max(0.0, min(1.0, (total + 1.0) / 2.0))
