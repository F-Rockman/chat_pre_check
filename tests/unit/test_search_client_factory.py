from __future__ import annotations

import importlib.util

import pytest

from chat_pre_check.infrastructure.resolvers.opensearch_client import OpenSearchClient
from chat_pre_check.infrastructure.resolvers.search_client_factory import (
    build_search_client,
    normalize_search_backend,
    resolve_search_backend,
)


def test_normalize_search_backend() -> None:
    assert normalize_search_backend(None) == "opensearch"
    assert normalize_search_backend("opensearch") == "opensearch"
    assert normalize_search_backend("elasticsearch") == "elasticsearch"
    assert normalize_search_backend("es") == "elasticsearch"
    with pytest.raises(ValueError):
        normalize_search_backend("unknown")


def test_resolve_search_backend_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    vector_cfg = {"search_backend": "opensearch"}
    monkeypatch.setenv("CHAT_PRE_CHECK_SEARCH_BACKEND", "es")
    assert resolve_search_backend(vector_cfg) == "elasticsearch"
    assert (
        resolve_search_backend(vector_cfg, backend_override="opensearch")
        == "opensearch"
    )


def test_build_search_client_opensearch() -> None:
    backend, client = build_search_client(
        vector_cfg={"search_backend": "opensearch"},
        base_url="http://localhost:9200",
        max_retries=0,
    )
    assert backend == "opensearch"
    assert isinstance(client, OpenSearchClient)


def test_build_search_client_elasticsearch_dependency_guard() -> None:
    has_elasticsearch = importlib.util.find_spec("elasticsearch") is not None
    if has_elasticsearch:
        backend, client = build_search_client(
            vector_cfg={"search_backend": "elasticsearch"},
            base_url="http://localhost:9200",
            max_retries=0,
        )
        assert backend == "elasticsearch"
        assert client is not None
    else:
        with pytest.raises(RuntimeError, match="package 'elasticsearch' is not installed"):
            build_search_client(
                vector_cfg={"search_backend": "elasticsearch"},
                base_url="http://localhost:9200",
                max_retries=0,
            )
