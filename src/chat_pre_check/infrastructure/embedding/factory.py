from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from chat_pre_check.infrastructure.embedding.e5_embedder import SentenceTransformerEmbedder
from chat_pre_check.infrastructure.embedding.http_embedder import OpenAICompatibleEmbeddingService


@dataclass(slots=True)
class EmbeddingRuntimeSpec:
    provider: str
    model: str
    dimension: int
    query_prefix: str
    passage_prefix: str


def build_embedder_from_vector_config(vector_cfg: dict[str, Any]):
    """
    根据 vector.json 的 embedding 段构建 embedder。

    兼容旧配置：
    - model_name/device 仍可用
    """
    embedding_cfg = vector_cfg.get("embedding", {})
    if not isinstance(embedding_cfg, dict):
        embedding_cfg = {}

    provider = (
        os.getenv("CHAT_PRE_CHECK_EMBED_PROVIDER")
        or embedding_cfg.get("provider")
        or "sentence_transformers"
    )
    provider = str(provider).strip().lower()

    model = (
        os.getenv("CHAT_PRE_CHECK_EMBED_MODEL")
        or embedding_cfg.get("model")
        or vector_cfg.get("model_name")
        or ""
    )
    model = str(model).strip()
    if not model:
        raise ValueError("embedding.model is required")

    query_prefix = str(embedding_cfg.get("query_prefix", "query: "))
    passage_prefix = str(embedding_cfg.get("passage_prefix", "passage: "))
    normalize = bool(embedding_cfg.get("normalize_embeddings", True))
    configured_dim = _to_positive_int(
        os.getenv("CHAT_PRE_CHECK_EMBED_DIM") or embedding_cfg.get("dimension")
    )

    if provider in {"sentence_transformers", "e5", "hf_st"}:
        device = (
            os.getenv("CHAT_PRE_CHECK_EMBED_DEVICE")
            or embedding_cfg.get("device")
            or vector_cfg.get("device")
            or "cpu"
        )
        embedder = SentenceTransformerEmbedder(
            model_name=model,
            device=str(device),
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            normalize_embeddings=normalize,
        )
        dimension = configured_dim or int(getattr(embedder, "dimension"))
        return embedder, EmbeddingRuntimeSpec(
            provider=provider,
            model=model,
            dimension=dimension,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
        )

    if provider in {"openai_embedding", "openai_compatible"}:
        api_key_env = str(embedding_cfg.get("api_key_env", "CHAT_PRE_CHECK_EMBED_API_KEY"))
        api_key = os.getenv(api_key_env, "").strip()
        if not api_key:
            raise ValueError(f"embedding api key not found in env: {api_key_env}")
        base_url = (
            os.getenv("CHAT_PRE_CHECK_EMBED_BASE_URL")
            or embedding_cfg.get("base_url")
            or ""
        )
        base_url = str(base_url).strip()
        if not base_url:
            raise ValueError("embedding.base_url is required for openai_compatible provider")
        embedder = OpenAICompatibleEmbeddingService(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_ms=int(embedding_cfg.get("timeout_ms", 3000)),
            endpoint_path=str(embedding_cfg.get("endpoint_path", "/embeddings")),
            api_key_header=str(embedding_cfg.get("api_key_header", "Authorization")),
            api_key_prefix=str(embedding_cfg.get("api_key_prefix", "Bearer ")),
            input_field=str(embedding_cfg.get("input_field", "input")),
            model_field=str(embedding_cfg.get("model_field", "model")),
            response_data_field=str(embedding_cfg.get("response_data_field", "data")),
            response_vector_field=str(embedding_cfg.get("response_vector_field", "embedding")),
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
        )
        if not configured_dim:
            raise ValueError("embedding.dimension is required for openai_compatible provider")
        return embedder, EmbeddingRuntimeSpec(
            provider=provider,
            model=model,
            dimension=configured_dim,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
        )

    raise ValueError(
        f"Unsupported embedding provider: {provider}. "
        "Use one of: sentence_transformers/e5/openai_compatible"
    )


def _to_positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0

