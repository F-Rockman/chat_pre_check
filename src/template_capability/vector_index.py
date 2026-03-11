from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from template_capability.openai_client import build_openai_client
from template_capability.scoring import mixed_terms


class VectorProvider(Protocol):
    """向量提供器接口。

    这层只负责“把文本编码成固定维度向量”，不负责检索。
    本地 provider 和远端 embedding 接口都遵守同一套协议。
    """

    dimension: int

    def prepare_documents(self, documents: dict[str, str]) -> None:
        """可选的语料预热步骤。

        本地 provider 可以利用模板文档构建词表或 IDF；
        远端 provider 通常什么都不需要做，可以保持 no-op。
        """

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class VectorSearchBackend(Protocol):
    """向量检索后端接口。"""

    def build(self, documents: dict[str, str]) -> None:
        ...

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        ...


@dataclass(slots=True)
class LocalHashVectorProvider:
    """轻量本地 hashing 向量。

    这是最朴素的本地实现，主要用于：
    - 兼容旧测试和旧行为
    - 在不需要更强本地效果时提供极简占位实现
    """

    dimension: int = 512

    def prepare_documents(self, documents: dict[str, str]) -> None:
        # 纯 hashing 不依赖语料统计信息。
        return None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for term in mixed_terms(text):
            bucket, sign = _signed_bucket(term, self.dimension)
            vector[bucket] += sign
        return _l2_normalize(vector)


@dataclass(slots=True)
class LocalTfidfVectorProvider:
    """默认本地向量实现。

    它不是大模型 embedding，但比单纯 hashing 更完整，核心做法是：
    1. 基于模板语料统计 term 的 IDF
    2. 对高价值 term 分配显式维度，避免碰撞
    3. 其余 term 走 overflow hashing，保留固定 512 维接口

    这种设计很适合你当前这类“模板数不大、领域词明确”的问数场景。
    """

    dimension: int = 512
    overflow_bucket_count: int = 128
    term_importance_power: float = 1.0
    idf_by_term: dict[str, float] = field(init=False, default_factory=dict)
    vocabulary: dict[str, int] = field(init=False, default_factory=dict)
    overflow_offset: int = field(init=False, default=0)
    total_docs: int = field(init=False, default=1)
    default_idf: float = field(init=False, default=1.0)

    def prepare_documents(self, documents: dict[str, str]) -> None:
        """根据模板文档构建本地词表和 IDF。"""
        self.total_docs = max(1, len(documents))
        document_terms = [Counter(_vector_terms(text)) for text in documents.values()]
        document_frequency: Counter[str] = Counter()
        for terms in document_terms:
            document_frequency.update(terms.keys())

        self.idf_by_term = {
            term: _bm25_idf(doc_freq, self.total_docs)
            for term, doc_freq in document_frequency.items()
        }
        self.default_idf = _bm25_idf(0, self.total_docs)

        # 高价值 term 走显式维度，减少模板核心词之间的哈希碰撞。
        term_importance: dict[str, float] = {}
        for terms in document_terms:
            for term, freq in terms.items():
                tf = 1.0 + math.log(freq)
                idf = self.idf_by_term.get(term, self.default_idf)
                term_importance[term] = term_importance.get(term, 0.0) + tf * (idf ** self.term_importance_power)

        reserved_overflow = min(max(16, self.overflow_bucket_count), max(1, self.dimension // 2))
        explicit_capacity = max(1, self.dimension - reserved_overflow)
        ranked_terms = sorted(term_importance.items(), key=lambda item: (-item[1], item[0]))
        self.vocabulary = {
            term: index
            for index, (term, _) in enumerate(ranked_terms[:explicit_capacity])
        }
        self.overflow_offset = len(self.vocabulary)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        term_counts = Counter(_vector_terms(text))
        if not term_counts:
            return vector

        overflow_buckets = max(0, self.dimension - self.overflow_offset)
        for term, freq in term_counts.items():
            weight = (1.0 + math.log(freq)) * self.idf_by_term.get(term, self.default_idf)
            explicit_index = self.vocabulary.get(term)
            if explicit_index is not None:
                vector[explicit_index] += weight
                continue
            if overflow_buckets <= 0:
                continue
            bucket, sign = _signed_bucket(term, overflow_buckets)
            vector[self.overflow_offset + bucket] += sign * weight
        return _l2_normalize(vector)


@dataclass(slots=True)
class RemoteEmbeddingProvider:
    """远端 embedding 接口适配器。

    它负责把任意兼容 `/embeddings` 风格接口的服务接到当前向量链路上。
    主流程仍然只认 `VectorProvider`，因此无需改 `engine.py`。
    """

    api_key: str
    base_url: str
    model: str
    dimension: int = 512
    timeout_seconds: float = 10.0
    batch_size: int = 32
    extra_body: dict[str, Any] = field(default_factory=dict)
    include_dimensions: bool = True
    client: Any | None = field(default=None, repr=False, compare=False)

    def prepare_documents(self, documents: dict[str, str]) -> None:
        # 远端 embedding 通常不需要本地预训练步骤。
        return None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), max(1, self.batch_size)):
            batch = texts[start : start + max(1, self.batch_size)]
            embeddings.extend(self._embed_batch(batch))
        return embeddings

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
            **self.extra_body,
        }
        if self.include_dimensions and self.dimension > 0:
            payload["dimensions"] = self.dimension
        client = self.client or build_openai_client(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
        )
        response = client.embeddings.create(**payload)
        data = getattr(response, "data", [])
        indexed_embeddings: list[tuple[int, list[float]]] = []
        for item in data:
            if hasattr(item, "embedding"):
                embedding = getattr(item, "embedding")
                index = int(getattr(item, "index", len(indexed_embeddings)))
            elif isinstance(item, dict):
                embedding = item.get("embedding")
                index = int(item.get("index", len(indexed_embeddings)))
            else:
                continue
            if not isinstance(embedding, list):
                continue
            indexed_embeddings.append((index, [float(value) for value in embedding]))
        indexed_embeddings.sort(key=lambda item: item[0])
        return [embedding for _, embedding in indexed_embeddings]


@dataclass(slots=True)
class InMemoryVectorIndex:
    """可替换的本地向量检索后端。"""

    provider: VectorProvider
    vectors: dict[str, list[float]] = field(default_factory=dict)

    def build(self, documents: dict[str, str]) -> None:
        # 先让 provider 基于模板语料做一次预热，再统一编码模板文档。
        self.provider.prepare_documents(documents)
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


# 兼容旧命名，避免外部已有代码直接 import `HashingVectorProvider` 时立刻断掉。
HashingVectorProvider = LocalHashVectorProvider


def _vector_terms(text: str) -> list[str]:
    """本地向量化使用的特征项。

    当前直接复用 `mixed_terms`，让 lexical 和 vector 至少共享一套稳定的基础切词。
    """
    return mixed_terms(text)


def _bm25_idf(doc_freq: int, total_docs: int) -> float:
    return math.log(1 + (total_docs - doc_freq + 0.5) / (doc_freq + 0.5))


def _signed_bucket(term: str, bucket_count: int) -> tuple[int, float]:
    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
    bucket = int.from_bytes(digest[:4], "big") % max(1, bucket_count)
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    return bucket, sign


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """返回 0-1 区间内的 cosine 分数。"""
    if not left or not right:
        return 0.0
    total = sum(lv * rv for lv, rv in zip(left, right, strict=True))
    return max(0.0, min(1.0, (total + 1.0) / 2.0))
