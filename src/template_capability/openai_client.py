from __future__ import annotations

import json
import re
from typing import Any


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_openai_client(
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
) -> Any:
    """延迟创建 OpenAI 客户端。

    这里不在模块导入时直接依赖 `openai`，这样核心规则链路在未安装 SDK 时仍可正常导入；
    只有真正调用远端模型时才要求环境里存在 `openai` 包。
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The `openai` package is required for LLM or remote embedding calls. "
            "Install it with `pip install openai`."
        ) from exc
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_seconds,
    )


def extract_chat_completion_content(response: Any) -> Any:
    """从 chat completion 响应里取出首条 message content。"""
    if hasattr(response, "choices"):
        choices = getattr(response, "choices", [])
    elif isinstance(response, dict):
        choices = response.get("choices", [])
    else:
        choices = []
    if not choices:
        return ""

    first = choices[0]
    if hasattr(first, "message"):
        message = getattr(first, "message")
    elif isinstance(first, dict):
        message = first.get("message", {})
    else:
        message = {}

    if hasattr(message, "content"):
        return getattr(message, "content")
    if isinstance(message, dict):
        return message.get("content", "")
    return ""


def parse_json_content(content: Any) -> dict[str, Any] | None:
    """把 message content 尽量解析成 JSON 对象。"""
    text = _content_to_text(content)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if match is None:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")).strip())
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text", "")).strip())
            else:
                parts.append(str(item).strip())
        return "".join(part for part in parts if part)
    return str(content).strip()
