from __future__ import annotations

from types import SimpleNamespace

from template_capability.fallback import OpenAICompatibleTemplateSlotResolver
from template_capability.models import SlotExtractorDefinition, TemplateDefinition
from template_capability.vector_index import RemoteEmbeddingProvider
from tools.generate_eval_corpus import generate_corpus


class FakeChatCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content)
                )
            ]
        )


class FakeEmbeddings:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        data = [
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in enumerate(self.vectors)
        ]
        return SimpleNamespace(data=data)


def test_template_slot_resolver_uses_openai_sdk_client():
    chat = FakeChatCompletions('{"slots": {"topn": 10}}')
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    resolver = OpenAICompatibleTemplateSlotResolver(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="fake-model",
        timeout_seconds=3.0,
        client=client,
    )
    template = TemplateDefinition(
        template_id="metric.rank.demo",
        query_mode="metric_query",
        description="查询演示指标排行",
        utterances=["近24小时演示指标前十"],
        required_slots=["topn"],
        optional_slots=[],
        must_terms=[["演示指标"]],
        negative_terms=[],
        slot_constraints={},
        slot_extractors={
            "topn": SlotExtractorDefinition(
                slot_name="topn",
                extractors=[
                    {
                        "type": "regex",
                        "patterns": [
                            {
                                "pattern": "(?:前|top)\\s*(\\d+)",
                                "group": 1,
                                "value_type": "int",
                            }
                        ],
                    }
                ],
            )
        },
        llm_slot_extraction={"enabled": True, "slots": ["topn"]},
    )

    suggestion = resolver.resolve_slots(
        input_text="近24小时演示指标前十",
        normalized_text="近24小时演示指标前十",
        template=template,
        current_slots={},
        missing_slots=["topn"],
    )

    assert suggestion is not None
    assert suggestion.slots == {"topn": 10}
    assert chat.calls
    assert chat.calls[0]["model"] == "fake-model"
    assert chat.calls[0]["response_format"]["type"] in {"json_schema", "json_object"}


def test_template_slot_resolver_prompt_treats_regex_patterns_as_atomic_authorizations():
    chat = FakeChatCompletions('{"slots": {"device_id": "device_a"}}')
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    resolver = OpenAICompatibleTemplateSlotResolver(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="fake-model",
        timeout_seconds=3.0,
        client=client,
    )
    template = TemplateDefinition(
        template_id="device.attribute.demo",
        query_mode="metric_query",
        description="查询指定属性下的设备信息",
        utterances=["属性A包含F的设备b信息", "属性B包含F的设备a信息"],
        required_slots=["device_id"],
        optional_slots=[],
        must_terms=[["设备"]],
        negative_terms=[],
        slot_constraints={},
        slot_extractors={
            "device_id": SlotExtractorDefinition(
                slot_name="device_id",
                extractors=[
                    {
                        "type": "regex",
                        "patterns": [
                            {
                                "pattern": "属性A包含F的设备b信息",
                                "value": "device_b",
                            },
                            {
                                "pattern": "属性B包含F的设备a信息",
                                "value": "device_a",
                            },
                        ],
                    }
                ],
            )
        },
        llm_slot_extraction={"enabled": True, "slots": ["device_id"]},
    )

    resolver.resolve_slots(
        input_text="属性A包含F的设备a信息",
        normalized_text="属性a包含f的设备a信息",
        template=template,
        current_slots={},
        missing_slots=["device_id"],
    )

    prompt = chat.calls[0]["messages"][1]["content"]
    assert '"value": "device_b"' in prompt
    assert '"value": "device_a"' in prompt
    assert "Never combine attribute/entity/object/value fragments" in prompt
    assert "attribute A with device a is not authorized" in prompt


def test_generate_corpus_uses_openai_sdk_client():
    chat = FakeChatCompletions(
        '{"matched":[{"text":"查询cpu大于80的设备列表","template_id":"device.cpu.over.list"}],'
        '"partial":[{"text":"查询cpu大于80的设备","template_id":"device.cpu.over.list"}],'
        '"unmatched":[{"text":"帮我分析cpu异常原因"}],'
        '"not_full_match":[{"text":"cpu异常怎么处理"}]}'
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat))

    payload = generate_corpus(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="fake-model",
        config_text='{"templates": []}',
        client=client,
    )

    assert payload["matched"][0]["template_id"] == "device.cpu.over.list"
    assert chat.calls
    assert chat.calls[0]["model"] == "fake-model"
    assert chat.calls[0]["response_format"] == {"type": "json_object"}


def test_remote_embedding_provider_uses_openai_sdk_client():
    embeddings = FakeEmbeddings(
        [
            [0.1, 0.2, 0.3],
            [0.3, 0.2, 0.1],
        ]
    )
    client = SimpleNamespace(embeddings=embeddings)
    provider = RemoteEmbeddingProvider(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="embedding-model",
        dimension=3,
        client=client,
    )

    vectors = provider.embed_texts(["cpu", "memory"])

    assert vectors == [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]]
    assert embeddings.calls
    assert embeddings.calls[0]["model"] == "embedding-model"
    assert embeddings.calls[0]["dimensions"] == 3
