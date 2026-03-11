from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Protocol

from template_capability.scoring import mixed_terms


class VectorProvider(Protocol):
    """向量提供器接口。

    这里故意只保留最小协议：
    - `dimension`: 声明输出维度
    - `embed_texts`: 批量把文本转成向量

    这样后续替换成外部 512 维向量服务时，不需要改动检索主流程。
    """

    dimension: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class VectorSearchBackend(Protocol):
    """向量检索后端接口。

    当前默认实现是内存版全量扫描；如果后续接 ANN 或外部检索服务，
    只需要实现同样的 `build/search` 两个方法。
    """

    def build(self, documents: dict[str, str]) -> None:
        ...

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        ...


@dataclass(slots=True)
class HashingVectorProvider:
    """本地默认向量提供器，接口和外部 512 维实现保持一致。"""

    dimension: int = 512

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # 外部接口通常天然支持批量编码，这里也保持同样的调用形态。
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        # 这不是语义 embedding，而是一个廉价的 hashing trick 占位实现。
        # 它的价值主要有两个：
        # 1. 本地无外部依赖时也能跑完整向量召回链路
        # 2. 逼着主流程始终按“可替换向量接口”设计，而不是写死某个供应商
        vector = [0.0] * self.dimension
        for term in mixed_terms(text):
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        # 统一做 L2 归一化，后续 cosine 相似度才有稳定意义。
        return [value / norm for value in vector]


@dataclass(slots=True)
class InMemoryVectorIndex:
    """可替换的本地向量检索后端。"""

    provider: VectorProvider
    vectors: dict[str, list[float]] = field(default_factory=dict)

    def build(self, documents: dict[str, str]) -> None:
        # build 只在引擎初始化时做一次，把模板文档预编码后常驻内存。
        doc_ids = list(documents.keys())
        embeddings = self.provider.embed_texts([documents[doc_id] for doc_id in doc_ids])
        self.vectors = {
            doc_id: embedding
            for doc_id, embedding in zip(doc_ids, embeddings, strict=True)
        }

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        if not self.vectors:
            return []
        # query 在线只编码一次，然后对当前模板全集做相似度排序。
        # 在 1000 级模板规模下，全量扫描仍然足够快。
        query_vector = self.provider.embed_texts([query_text])[0]
        results = [
            (doc_id, _cosine_similarity(query_vector, vector))
            for doc_id, vector in self.vectors.items()
        ]
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:top_k]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """返回 0-1 区间内的 cosine 分数。"""
    if not left or not right:
        return 0.0
    total = sum(lv * rv for lv, rv in zip(left, right, strict=True))
    # 标准 cosine 是 [-1, 1]，这里线性映射到 [0, 1]，方便和其他子分统一融合。
    return max(0.0, min(1.0, (total + 1.0) / 2.0))
