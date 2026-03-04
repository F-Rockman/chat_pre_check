from __future__ import annotations

import json
from typing import Any, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np


class OpenAICompatibleEmbeddingService:
    """OpenAI 兼容 Embedding HTTP 客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_ms: int = 3000,
        endpoint_path: str = "/embeddings",
        api_key_header: str = "Authorization",
        api_key_prefix: str = "Bearer ",
        input_field: str = "input",
        model_field: str = "model",
        response_data_field: str = "data",
        response_vector_field: str = "embedding",
        query_prefix: str = "",
        passage_prefix: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_ms = max(200, int(timeout_ms))
        self.endpoint_path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
        self.api_key_header = str(api_key_header).strip() or "Authorization"
        self.api_key_prefix = str(api_key_prefix)
        self.input_field = str(input_field).strip() or "input"
        self.model_field = str(model_field).strip() or "model"
        self.response_data_field = str(response_data_field).strip() or "data"
        self.response_vector_field = str(response_vector_field).strip() or "embedding"
        self.query_prefix = str(query_prefix)
        self.passage_prefix = str(passage_prefix)
        self._dimension: int | None = None

    @property
    def dimension(self) -> int | None:
        return self._dimension

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        payload_texts = [f"{self.query_prefix}{text}" for text in texts]
        return self._encode(payload_texts)

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        payload_texts = [f"{self.passage_prefix}{text}" for text in texts]
        return self._encode(payload_texts)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        endpoint = f"{self.base_url}{self.endpoint_path}"
        payload = {
            self.model_field: self.model,
            self.input_field: list(texts),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        auth_value = f"{self.api_key_prefix}{self.api_key}" if self.api_key_prefix else self.api_key
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                self.api_key_header: auth_value,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_ms / 1000.0) as resp:
                text = resp.read().decode("utf-8")
        except URLError as exc:
            raise RuntimeError(f"embedding_request_failed:{exc}") from exc
        except Exception as exc:  # pragma: no cover - network dependent
            raise RuntimeError(f"embedding_request_failed:{exc}") from exc
        data = json.loads(text)
        rows = data.get(self.response_data_field, [])
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("embedding_response_missing_data")

        vectors: list[list[float]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            vector = item.get(self.response_vector_field, [])
            if not isinstance(vector, list) or not vector:
                continue
            vectors.append([float(value) for value in vector])
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding_vector_count_mismatch:expected={len(texts)} actual={len(vectors)}"
            )
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] <= 0:
            raise RuntimeError("embedding_response_invalid_shape")
        self._dimension = int(matrix.shape[1])
        return matrix

