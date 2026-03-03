from __future__ import annotations

import time
from typing import Any


class ElasticsearchClient:
    """Elasticsearch 访问封装：索引管理、向量检索、文本检索。"""

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
        timeout: int = 5,
        max_retries: int = 1,
        retry_backoff_sec: float = 0.2,
    ) -> None:
        try:
            from elasticsearch import Elasticsearch
        except Exception as exc:  # pragma: no cover - import guard path
            raise RuntimeError(
                "Elasticsearch backend selected but package 'elasticsearch' is not installed. "
                "Install it with: pip install elasticsearch>=8.15.0"
            ) from exc

        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        auth = (username, password) if username and password else None
        self.client = Elasticsearch(
            hosts=[base_url],
            basic_auth=auth,
            headers=headers or None,
            verify_certs=False,
            request_timeout=timeout,
        )
        self.max_retries = max_retries
        self.retry_backoff_sec = retry_backoff_sec

    def ping(self) -> bool:
        return bool(self._with_retry("ping", self.client.ping))

    def index_exists(self, index_name: str) -> bool:
        return bool(
            self._with_retry(
                "indices.exists",
                lambda: self.client.indices.exists(index=index_name),
            )
        )

    def ensure_vector_index(self, index_name: str, dimension: int) -> None:
        if self.index_exists(index_name):
            return
        # ES8 向量索引使用 dense_vector + cosine。
        body = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "scene_id": {"type": "keyword"},
                    "template_id": {"type": "keyword"},
                    "text": {"type": "text"},
                    "metadata": {"type": "object", "enabled": True},
                    "vector": {
                        "type": "dense_vector",
                        "dims": dimension,
                        "index": True,
                        "similarity": "cosine",
                    },
                }
            },
        }
        self._with_retry(
            "indices.create",
            lambda: self.client.indices.create(index=index_name, body=body),
        )

    def bulk_index(self, index_name: str, docs: list[dict[str, Any]]) -> None:
        operations = []
        for doc in docs:
            operations.append({"index": {"_index": index_name, "_id": doc["id"]}})
            operations.append(doc)
        if operations:
            self._with_retry(
                "bulk",
                lambda: self.client.bulk(operations=operations, refresh=True),
            )

    def knn_search(
        self,
        index_name: str,
        vector: list[float],
        topk: int,
        must_filters: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        must_filters = must_filters or []
        body = {
            "size": topk,
            "query": {
                "bool": {
                    "must": [
                        {
                            "knn": {
                                "field": "vector",
                                "query_vector": vector,
                                "k": topk,
                                "num_candidates": max(topk * 4, 50),
                            }
                        }
                    ],
                    "filter": must_filters,
                }
            },
        }
        try:
            response = self._with_retry(
                "search_knn",
                lambda: self.client.search(index=index_name, body=body),
            )
            return response.get("hits", {}).get("hits", [])
        except Exception:
            # 兼容不支持 knn query 的集群，降级为 script_score。
            fallback = {
                "size": topk,
                "query": {
                    "script_score": {
                        "query": {
                            "bool": {
                                "filter": must_filters,
                            }
                        },
                        "script": {
                            "source": "cosineSimilarity(params.query_vector, 'vector') + 1.0",
                            "params": {"query_vector": vector},
                        },
                    }
                },
            }
            response = self._with_retry(
                "search_knn_script_score",
                lambda: self.client.search(index=index_name, body=fallback),
            )
            return response.get("hits", {}).get("hits", [])

    def text_search(
        self,
        index_name: str,
        text: str,
        topk: int,
        must_filters: list[dict[str, Any]] | None = None,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        must_filters = must_filters or []
        fields = fields or ["text^2", "metadata.name"]
        body = {
            "size": topk,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": text,
                                "fields": fields,
                            }
                        }
                    ],
                    "filter": must_filters,
                }
            },
        }
        response = self._with_retry(
            "search_text",
            lambda: self.client.search(index=index_name, body=body),
        )
        return response.get("hits", {}).get("hits", [])

    def _with_retry(self, operation: str, fn):
        # 轻量重试：用于短暂网络抖动和节点过载。
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_sec * (attempt + 1))
        raise RuntimeError(f"Elasticsearch operation failed: {operation}: {last_error}")
