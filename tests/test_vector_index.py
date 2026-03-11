from __future__ import annotations

from template_capability.vector_index import (
    InMemoryVectorIndex,
    LocalHashVectorProvider,
    LocalTfidfVectorProvider,
)


def test_local_tfidf_vector_provider_prefers_related_template():
    backend = InMemoryVectorIndex(provider=LocalTfidfVectorProvider(dimension=64))
    backend.build(
        {
            "device.cpu.over.list": "查询 cpu 大于 80 的设备列表 cpu 超过 阈值",
            "device.memory.over.list": "查询 内存 大于 70 的设备列表 memory 超过 阈值",
        }
    )

    ranked = backend.search("cpu 高于 80 的设备有哪些", top_k=2)

    assert ranked[0][0] == "device.cpu.over.list"
    assert ranked[0][1] > ranked[1][1]


def test_local_tfidf_vector_provider_keeps_fixed_dimension():
    provider = LocalTfidfVectorProvider(dimension=32)
    provider.prepare_documents(
        {
            "a": "查询 最近 cpu 大于 80 的设备列表",
            "b": "查询 最近 内存 大于 70 的设备列表",
        }
    )

    vectors = provider.embed_texts(["cpu 大于 80", "内存 大于 70"])

    assert len(vectors) == 2
    assert all(len(vector) == 32 for vector in vectors)
    assert any(any(value != 0.0 for value in vector) for vector in vectors)


def test_local_hash_vector_provider_remains_available():
    backend = InMemoryVectorIndex(provider=LocalHashVectorProvider(dimension=32))
    backend.build(
        {
            "tmpl.cpu": "cpu 大于 80 设备列表",
            "tmpl.memory": "内存 大于 70 设备列表",
        }
    )

    ranked = backend.search("cpu 大于 80 的设备", top_k=2)

    assert ranked[0][0] == "tmpl.cpu"
