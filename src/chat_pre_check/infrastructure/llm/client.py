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
    """最小 OpenAI 兼容聊天客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_ms: int = 2500,
        enable_thinking: bool = False,
        force_json_response: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_ms = max(200, int(timeout_ms))
        self.enable_thinking = bool(enable_thinking)
        self.force_json_response = bool(force_json_response)

    def chat_json(self, *, system_prompt: str, user_prompt: str, max_output_tokens: int) -> ChatResponse:
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "max_tokens": max(32, int(max_output_tokens)),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        payload["enable_thinking"] = self.enable_thinking
        if self.force_json_response:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
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
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("llm_response_missing_choices")
        message = choices[0].get("message", {})
        content = str(message.get("content", "")).strip()
        if not content:
            raise RuntimeError("llm_response_empty_content")
        return ChatResponse(content=content, latency_ms=latency_ms, raw=data)
