from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from chat_pre_check.infrastructure.llm.client import OpenAICompatibleChatClient


@dataclass(slots=True)
class FlowLLMResult:
    flow_type: str
    scene: str | None
    slots: dict[str, Any]
    confidence: float
    latency_ms: float
    raw_text: str


class FlowLLMAssistService:
    """Flow/Scene 单次增强服务。"""

    def __init__(
        self,
        *,
        client: OpenAICompatibleChatClient | None,
        enabled: bool = False,
        max_input_chars: int = 350,
        max_output_tokens: int = 120,
    ) -> None:
        self.client = client
        self.enabled = bool(enabled and client is not None)
        self.max_input_chars = max(60, int(max_input_chars))
        self.max_output_tokens = max(64, int(max_output_tokens))

    def infer_flow(
        self,
        *,
        input_text: str,
        flow_candidates: list[tuple[str, float]],
        scene_candidates: list[tuple[str, float]],
        slots: dict[str, Any],
    ) -> FlowLLMResult | None:
        if not self.enabled or self.client is None:
            return None
        text = str(input_text or "").strip()
        if not text:
            return None
        text = text[: self.max_input_chars]
        system_prompt = (
            "你是对话分流助手。"
            "请仅返回一行 JSON，不要输出额外解释。"
            "字段: flow_type(scene/report/direct/unknown), scene, slots, confidence。"
            "flow_type 只能是 query/report/direct/unknown。"
            "confidence 在 0 到 1。"
        )
        user_payload = {
            "input_text": text,
            "flow_candidates": flow_candidates[:2],
            "scene_candidates": scene_candidates[:3],
            "slots": slots,
        }
        user_prompt = json.dumps(user_payload, ensure_ascii=False)
        response = self.client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self.max_output_tokens,
        )
        payload = self._parse_json(response.content)
        if not isinstance(payload, dict):
            return None

        flow_type = self._normalize_flow_type(payload.get("flow_type"))
        if flow_type is None:
            return None
        scene = payload.get("scene")
        scene_value = str(scene).strip() if scene is not None else None
        slots_value = payload.get("slots", {})
        if not isinstance(slots_value, dict):
            slots_value = {}
        confidence = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        return FlowLLMResult(
            flow_type=flow_type,
            scene=scene_value if scene_value else None,
            slots=slots_value,
            confidence=confidence,
            latency_ms=response.latency_ms,
            raw_text=response.content,
        )

    @staticmethod
    def _normalize_flow_type(raw_value: Any) -> str | None:
        text = str(raw_value or "").strip().lower()
        if not text:
            return None
        if text in {"query", "report", "direct", "unknown"}:
            return text
        if "report" in text or text in {"task", "generation"}:
            return "report"
        if "query" in text or "analysis" in text or "ask" in text:
            return "query"
        if "direct" in text:
            return "direct"
        if "unknown" in text:
            return "unknown"
        return None

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            lines = [line for line in raw.splitlines() if not line.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            left = raw.find("{")
            right = raw.rfind("}")
            if left < 0 or right <= left:
                return None
            try:
                return json.loads(raw[left : right + 1])
            except json.JSONDecodeError:
                return None
