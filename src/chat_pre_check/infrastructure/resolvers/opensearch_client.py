from __future__ import annotations

import time
from typing import Any

from opensearchpy import OpenSearch


class OpenSearchClient:
    """OpenSearch 访问封装：索引管理、向量检索、文本检索。"""

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
        http_auth = None
        headers = {}
        if username and password:
            http_auth = (username, password)
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self.client = OpenSearch(
            hosts=[base_url],
            http_auth=http_auth,
            headers=headers,
            use_ssl=base_url.startswith("https"),
            verify_certs=False,
            timeout=timeout,
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
        # 统一索引映射，向量字段使用 knn_vector。
        body = {
            "settings": {
                "index": {
                    "knn": True,
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                }
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "scene_id": {"type": "keyword"},
                    "template_id": {"type": "keyword"},
                    "text": {"type": "text"},
                    "metadata": {"type": "object", "enabled": True},
                    "vector": {
                        "type": "knn_vector",
                        "dimension": dimension,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib",
                        },
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
                lambda: self.client.bulk(body=operations, refresh=True),
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
                                "vector": {
                                    "vector": vector,
                                    "k": topk,
                                }
                            }
                        }
                    ],
                    "filter": must_filters,
                }
            },
        }
        response = self._with_retry(
            "search_knn",
            lambda: self.client.search(index=index_name, body=body),
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
        raise RuntimeError(f"OpenSearch operation failed: {operation}: {last_error}")
