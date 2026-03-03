from __future__ import annotations

from typing import Sequence

import numpy as np


class E5Embedder:
    """E5 向量编码器封装，惰性加载模型。"""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        # E5 推荐 query/passsage 双前缀输入格式。
        prefixed = [f"query: {text}" for text in texts]
        return self._encode(prefixed)

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        prefixed = [f"passage: {text}" for text in texts]
        return self._encode(prefixed)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        matrix = self.model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(matrix, dtype=np.float32)
