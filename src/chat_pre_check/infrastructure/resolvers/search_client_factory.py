from __future__ import annotations

import os
from typing import Any

from chat_pre_check.infrastructure.resolvers.elasticsearch_client import ElasticsearchClient
from chat_pre_check.infrastructure.resolvers.opensearch_client import OpenSearchClient


SEARCH_BACKEND_OPENSEARCH = "opensearch"
SEARCH_BACKEND_ELASTICSEARCH = "elasticsearch"
_BACKEND_ALIAS = {
    "opensearch": SEARCH_BACKEND_OPENSEARCH,
    "elasticsearch": SEARCH_BACKEND_ELASTICSEARCH,
    "es": SEARCH_BACKEND_ELASTICSEARCH,
}


def normalize_search_backend(search_backend: str | None) -> str:
    """归一化后端名称，支持 es 别名。"""
    backend = (search_backend or "").strip().lower()
    if backend == "":
        return SEARCH_BACKEND_OPENSEARCH
    mapped = _BACKEND_ALIAS.get(backend)
    if mapped:
        return mapped
    raise ValueError(
        f"Unsupported search backend: {search_backend}. "
        "Use one of: opensearch, elasticsearch (or es)."
    )


def resolve_search_backend(
    vector_cfg: dict[str, Any],
    *,
    backend_override: str | None = None,
) -> str:
    # 优先级：函数参数 > 环境变量 > 配置文件 > 默认值。
    candidate = (
        backend_override
        or os.getenv("CHAT_PRE_CHECK_SEARCH_BACKEND")
        or vector_cfg.get("search_backend")
        or SEARCH_BACKEND_OPENSEARCH
    )
    return normalize_search_backend(candidate)


def build_search_client(
    *,
    vector_cfg: dict[str, Any],
    base_url: str,
    username: str | None = None,
    password: str | None = None,
    bearer_token: str | None = None,
    timeout: int = 5,
    max_retries: int = 1,
    retry_backoff_sec: float = 0.2,
    backend_override: str | None = None,
):
    """按后端类型构建搜索客户端实例。"""
    backend = resolve_search_backend(vector_cfg, backend_override=backend_override)
    if backend == SEARCH_BACKEND_OPENSEARCH:
        client = OpenSearchClient(
            base_url=base_url,
            username=username,
            password=password,
            bearer_token=bearer_token,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
        )
        return backend, client

    if backend == SEARCH_BACKEND_ELASTICSEARCH:
        client = ElasticsearchClient(
            base_url=base_url,
            username=username,
            password=password,
            bearer_token=bearer_token,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_sec=retry_backoff_sec,
        )
        return backend, client

    # 防御性分支，避免未来扩展时静默落空。
    raise ValueError(f"Unsupported search backend: {backend}")
