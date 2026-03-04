from __future__ import annotations

from typing import Sequence

import numpy as np


class SentenceTransformerEmbedder:
    """SentenceTransformer 向量编码器封装，支持 query/passage 前缀。"""

    def __init__(
        self,
        model_name: str,
        device: str = "cpu",
        query_prefix: str = "",
        passage_prefix: str = "",
        normalize_embeddings: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.normalize_embeddings = bool(normalize_embeddings)
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def dimension(self) -> int:
        get_dim = getattr(self.model, "get_sentence_embedding_dimension", None)
        if callable(get_dim):
            dim = int(get_dim())
            if dim > 0:
                return dim
        # 回退：未知模型时通过一次最小编码探测维度。
        matrix = self._encode(["probe"])
        return int(matrix.shape[1])

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [f"{self.query_prefix}{text}" for text in texts]
        return self._encode(prefixed)

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [f"{self.passage_prefix}{text}" for text in texts]
        return self._encode(prefixed)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        matrix = self.model.encode(
            list(texts),
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(matrix, dtype=np.float32)


class E5Embedder(SentenceTransformerEmbedder):
    """E5 兼容包装：保留原类名，默认前缀符合 E5 规范。"""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        super().__init__(
            model_name=model_name,
            device=device,
            query_prefix="query: ",
            passage_prefix="passage: ",
            normalize_embeddings=True,
        )
