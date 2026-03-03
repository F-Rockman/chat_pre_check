from __future__ import annotations

import numpy as np

from chat_pre_check.infrastructure.retrievers.opensearch_vector_retriever import (
    OpenSearchVectorRetriever,
)


class _CountingEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    def encode_queries(self, texts):
        self.calls += len(texts)
        return np.array([[1.0, 0.0, 0.0, 0.0] for _ in texts], dtype=np.float32)


class _DummyClient:
    def knn_search(self, index_name, vector, topk, must_filters=None):
        return []

    def text_search(self, index_name, text, topk, must_filters=None, fields=None):
        return []


def test_query_vector_cache_reused_across_search_steps() -> None:
    embedder = _CountingEmbedder()
    retriever = OpenSearchVectorRetriever(
        client=_DummyClient(),
        embedder=embedder,
        scene_index="scene_v1",
        template_index="template_v1",
        seed_case_index="seed_v1",
        query_vector_cache_size=16,
    )

    query = "近24小时告警top10"
    retriever.search_scene(query, topk=3)
    retriever.search_template("alarm.query", query, topk=3)
    retriever.search_seed_cases(query, topk=3)
    assert embedder.calls == 1
