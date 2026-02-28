from __future__ import annotations

from chat_pre_check.domain.interfaces import Embedder
from chat_pre_check.domain.models import SearchHit
from chat_pre_check.infrastructure.resolvers.opensearch_client import OpenSearchClient


class OpenSearchVectorRetriever:
    def __init__(
        self,
        client: OpenSearchClient,
        embedder: Embedder,
        scene_index: str,
        template_index: str,
        seed_case_index: str | None = None,
        fusion_alpha: float = 0.7,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.scene_index = scene_index
        self.template_index = template_index
        self.seed_case_index = seed_case_index
        self.fusion_alpha = fusion_alpha

    def search_scene(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        query_vector = self.embedder.encode_queries([query_text])[0].tolist()
        vector_hits = self.client.knn_search(
            index_name=self.scene_index,
            vector=query_vector,
            topk=topk,
        )
        text_hits = self.client.text_search(
            index_name=self.scene_index,
            text=query_text,
            topk=topk,
        )
        return self._fuse_hits(vector_hits, text_hits)

    def search_template(self, scene_id: str, query_text: str, topk: int = 5) -> list[SearchHit]:
        query_vector = self.embedder.encode_queries([query_text])[0].tolist()
        filters = [{"term": {"scene_id": scene_id}}]
        vector_hits = self.client.knn_search(
            index_name=self.template_index,
            vector=query_vector,
            topk=topk,
            must_filters=filters,
        )
        text_hits = self.client.text_search(
            index_name=self.template_index,
            text=query_text,
            topk=topk,
            must_filters=filters,
        )
        return self._fuse_hits(vector_hits, text_hits)

    def search_seed_cases(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        if not self.seed_case_index:
            return []
        query_vector = self.embedder.encode_queries([query_text])[0].tolist()
        vector_hits = self.client.knn_search(
            index_name=self.seed_case_index,
            vector=query_vector,
            topk=topk,
        )
        text_hits = self.client.text_search(
            index_name=self.seed_case_index,
            text=query_text,
            topk=topk,
        )
        return self._fuse_hits(vector_hits, text_hits)

    def _fuse_hits(self, vector_hits: list[dict], text_hits: list[dict]) -> list[SearchHit]:
        hit_map: dict[str, dict] = {}

        def merge_score(hit: dict, vector_part: bool) -> None:
            doc_id = hit.get("_id")
            if doc_id is None:
                return
            source = hit.get("_source", {})
            score = float(hit.get("_score", 0.0))
            if doc_id not in hit_map:
                hit_map[doc_id] = {"vector": 0.0, "text": 0.0, "source": source}
            key = "vector" if vector_part else "text"
            hit_map[doc_id][key] = max(hit_map[doc_id][key], score)

        for hit in vector_hits:
            merge_score(hit, vector_part=True)
        for hit in text_hits:
            merge_score(hit, vector_part=False)

        vector_max = max((item["vector"] for item in hit_map.values()), default=1.0) or 1.0
        text_max = max((item["text"] for item in hit_map.values()), default=1.0) or 1.0

        merged: list[SearchHit] = []
        for doc_id, value in hit_map.items():
            vector_norm = value["vector"] / vector_max
            text_norm = value["text"] / text_max
            score = self.fusion_alpha * vector_norm + (1 - self.fusion_alpha) * text_norm
            metadata = dict(value["source"].get("metadata", {}))
            if "scene_id" in value["source"]:
                metadata["scene_id"] = value["source"]["scene_id"]
            if "template_id" in value["source"]:
                metadata["template_id"] = value["source"]["template_id"]
            merged.append(SearchHit(doc_id=doc_id, score=score, metadata=metadata))

        merged.sort(key=lambda item: item.score, reverse=True)
        return merged
