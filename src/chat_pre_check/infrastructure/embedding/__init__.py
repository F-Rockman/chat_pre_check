"""Embedding adapters."""

from chat_pre_check.infrastructure.embedding.e5_embedder import (
    E5Embedder,
    SentenceTransformerEmbedder,
)
from chat_pre_check.infrastructure.embedding.factory import (
    EmbeddingRuntimeSpec,
    build_embedder_from_vector_config,
)
from chat_pre_check.infrastructure.embedding.http_embedder import (
    OpenAICompatibleEmbeddingService,
)

__all__ = [
    "E5Embedder",
    "SentenceTransformerEmbedder",
    "OpenAICompatibleEmbeddingService",
    "EmbeddingRuntimeSpec",
    "build_embedder_from_vector_config",
]
