from __future__ import annotations

import uuid

import numpy as np
import pytest

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.domain.models import RouteRequest
from chat_pre_check.infrastructure.resolvers.opensearch_client import OpenSearchClient
from chat_pre_check.infrastructure.retrievers.opensearch_vector_retriever import (
    OpenSearchVectorRetriever,
)


class DummyEmbedder:
    def encode_queries(self, texts):
        return np.array([[1.0, 0.0, 0.0, 0.0] for _ in texts], dtype=np.float32)

    def encode_passages(self, texts):
        vectors = []
        for text in texts:
            if "alarm.query" in text or "告警" in text:
                vectors.append([1.0, 0.0, 0.0, 0.0])
            else:
                vectors.append([0.0, 1.0, 0.0, 0.0])
        return np.array(vectors, dtype=np.float32)


@pytest.mark.integration
def test_opensearch_vector_retriever_search(os_base_url):
    client = OpenSearchClient(base_url=os_base_url)
    if not client.ping():
        pytest.skip("OpenSearch not available")

    suffix = uuid.uuid4().hex[:8]
    scene_index = f"it_scene_{suffix}"
    template_index = f"it_tpl_{suffix}"
    client.ensure_vector_index(scene_index, dimension=4)
    client.ensure_vector_index(template_index, dimension=4)

    client.bulk_index(
        scene_index,
        [
            {
                "id": "scene_alarm_1",
                "scene_id": "alarm.query",
                "text": "告警 查询 场景",
                "metadata": {"scene_id": "alarm.query"},
                "vector": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "id": "scene_device_1",
                "scene_id": "device.query",
                "text": "设备 查询 场景",
                "metadata": {"scene_id": "device.query"},
                "vector": [0.0, 1.0, 0.0, 0.0],
            },
        ],
    )
    client.bulk_index(
        template_index,
        [
            {
                "id": "tpl_alarm_topn_1",
                "scene_id": "alarm.query",
                "template_id": "tpl_alarm_topn",
                "text": "查近24小时核心网告警Top10",
                "metadata": {"scene_id": "alarm.query", "template_id": "tpl_alarm_topn"},
                "vector": [1.0, 0.0, 0.0, 0.0],
            }
        ],
    )

    retriever = OpenSearchVectorRetriever(
        client=client,
        embedder=DummyEmbedder(),
        scene_index=scene_index,
        template_index=template_index,
    )
    scene_hits = retriever.search_scene("告警 查询", topk=2)
    assert scene_hits
    assert scene_hits[0].metadata["scene_id"] == "alarm.query"

    template_hits = retriever.search_template("alarm.query", "告警 top10", topk=2)
    assert template_hits
    assert template_hits[0].metadata["template_id"] == "tpl_alarm_topn"


@pytest.mark.integration
def test_unavailable_opensearch_returns_data_unavailable():
    engine = build_engine(
        config_dir="configs",
        os_url="http://127.0.0.1:1",
    )
    decision = engine.route(RouteRequest(input_text="查设备10.2.3.4状态"))
    payload = decision.to_dict()
    assert payload["type"] == "refuse"
    assert payload["out_of_scope_reason"] == "data_unavailable"
