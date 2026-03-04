from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class ChatResponse:
    content: str
    latency_ms: float
    raw: dict[str, Any]


class OpenAICompatibleChatClient:
    """可配置的 OpenAI 兼容聊天客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_ms: int = 2500,
        enable_thinking: bool = False,
        force_json_response: bool = True,
        endpoint_path: str = "/chat/completions",
        api_key_header: str = "Authorization",
        api_key_prefix: str = "Bearer ",
        model_field: str = "model",
        messages_field: str = "messages",
        max_tokens_field: str = "max_tokens",
        request_extra: dict[str, Any] | None = None,
        response_content_path: list[Any] | str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_ms = max(200, int(timeout_ms))
        self.enable_thinking = bool(enable_thinking)
        self.force_json_response = bool(force_json_response)
        self.endpoint_path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
        self.api_key_header = str(api_key_header).strip() or "Authorization"
        self.api_key_prefix = str(api_key_prefix)
        self.model_field = str(model_field).strip() or "model"
        self.messages_field = str(messages_field).strip() or "messages"
        self.max_tokens_field = str(max_tokens_field).strip() or "max_tokens"
        self.request_extra = request_extra if isinstance(request_extra, dict) else {}
        self.response_content_path = self._normalize_response_path(response_content_path)

    def chat_json(self, *, system_prompt: str, user_prompt: str, max_output_tokens: int) -> ChatResponse:
        endpoint = f"{self.base_url}{self.endpoint_path}"
        payload: dict[str, Any] = dict(self.request_extra)
        payload[self.model_field] = self.model
        payload.setdefault("temperature", 0.0)
        payload[self.max_tokens_field] = max(32, int(max_output_tokens))
        payload[self.messages_field] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        payload["enable_thinking"] = self.enable_thinking
        if self.force_json_response:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        auth_value = f"{self.api_key_prefix}{self.api_key}" if self.api_key_prefix else self.api_key
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                self.api_key_header: auth_value,
                "Content-Type": "application/json",
            },
        )
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout_ms / 1000.0) as resp:
                text = resp.read().decode("utf-8")
        except URLError as exc:
            raise RuntimeError(f"llm_request_failed:{exc}") from exc
        except Exception as exc:  # pragma: no cover - network dependent
            raise RuntimeError(f"llm_request_failed:{exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        data = json.loads(text)
        content = self._extract_content(data)
        if not content:
            raise RuntimeError("llm_response_empty_content")
        return ChatResponse(content=content, latency_ms=latency_ms, raw=data)

    def _extract_content(self, payload: dict[str, Any]) -> str:
        value: Any = payload
        for token in self.response_content_path:
            if isinstance(token, int):
                if not isinstance(value, list) or token >= len(value):
                    return ""
                value = value[token]
                continue
            if not isinstance(value, dict):
                return ""
            if token not in value:
                return ""
            value = value[token]
        return str(value or "").strip()

    @staticmethod
    def _normalize_response_path(path: list[Any] | str | None) -> list[Any]:
        if isinstance(path, list) and path:
            return [int(item) if isinstance(item, int) or str(item).isdigit() else str(item) for item in path]
        if isinstance(path, str) and path.strip():
            tokens: list[Any] = []
            for part in path.split("."):
                token = part.strip()
                if not token:
                    continue
                tokens.append(int(token) if token.isdigit() else token)
            if tokens:
                return tokens
        return ["choices", 0, "message", "content"]
