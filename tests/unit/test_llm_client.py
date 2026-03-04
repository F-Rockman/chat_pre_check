from __future__ import annotations

import json

from chat_pre_check.infrastructure.llm.client import OpenAICompatibleChatClient


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")


def test_llm_client_supports_custom_response_content_path(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001, ANN202
        return _FakeResponse({"result": {"answer": "ok"}})

    monkeypatch.setattr("chat_pre_check.infrastructure.llm.client.urlopen", fake_urlopen)
    client = OpenAICompatibleChatClient(
        base_url="https://example.com/v1",
        api_key="k",
        model="m",
        response_content_path="result.answer",
    )
    response = client.chat_json(system_prompt="s", user_prompt="u", max_output_tokens=32)
    assert response.content == "ok"


def test_llm_client_supports_custom_request_fields(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):  # noqa: ANN001, ANN202
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("chat_pre_check.infrastructure.llm.client.urlopen", fake_urlopen)
    client = OpenAICompatibleChatClient(
        base_url="https://example.com",
        api_key="token",
        model="qwen",
        endpoint_path="/custom/chat",
        api_key_header="X-API-Key",
        api_key_prefix="",
        model_field="model_id",
        messages_field="dialog",
        max_tokens_field="output_tokens",
        request_extra={"temperature": 0.1},
    )
    response = client.chat_json(system_prompt="s", user_prompt="u", max_output_tokens=64)
    assert response.content == "ok"
    assert captured["url"] == "https://example.com/custom/chat"
    assert captured["headers"].get("X-api-key") == "token"
    assert captured["body"]["model_id"] == "qwen"
    assert captured["body"]["output_tokens"] == 64
    assert isinstance(captured["body"]["dialog"], list)
