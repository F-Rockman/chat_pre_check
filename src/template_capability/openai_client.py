from __future__ import annotations

import json
import os
import re
from typing import Any


_THINK_TAG_RE = re.compile(r"<thi(?:nk|ngk)\b[^>]*>.*?</thi(?:nk|ngk)>", re.IGNORECASE | re.DOTALL)
_THINKING_TAG_RE = re.compile(r"<thinking\b[^>]*>.*?</thinking>", re.IGNORECASE | re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


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
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "The `openai` package is required for LLM or remote embedding calls. "
            "Install it with `pip install openai`."
        ) from exc
    verify_ssl = not _env_truthy("TEMPLATE_CAPABILITY_INSECURE_SSL") and not _env_truthy("OPENAI_INSECURE_SSL")
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_seconds,
        http_client=httpx.Client(
            verify=verify_ssl,
            timeout=timeout_seconds,
        ),
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
    raw_text = _content_to_text(content)
    text = _cleanup_model_text(raw_text)
    if not text:
        return None
    payload = _try_parse_object(text)
    if payload is not None:
        return payload
    for block in _CODE_BLOCK_RE.findall(text):
        payload = _try_parse_object(str(block).strip())
        if payload is not None:
            return payload
    json_block = _extract_balanced_json_object(text)
    if not json_block:
        return None
    return _try_parse_object(json_block)


def _cleanup_model_text(text: str) -> str:
    cleaned = str(text).lstrip("\ufeff").strip()
    if not cleaned:
        return ""
    return _THINK_TAG_RE.sub("", _THINKING_TAG_RE.sub("", cleaned)).strip()


def _try_parse_object(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_balanced_json_object(text: str) -> str:
    start = -1
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if start < 0:
            if char == "{":
                start = index
                depth = 1
            continue
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
