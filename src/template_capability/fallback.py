from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib import request

from template_capability.models import MatchStatus, TemplateCandidate, TemplateDefinition


@dataclass(slots=True)
class FallbackSuggestion:
    """模板选择 fallback 的统一返回结构。"""
    template_id: str | int
    status: MatchStatus
    score: float
    query_mode: str | None
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SlotFallbackSuggestion:
    """模板级 LLM 补参的统一返回结构。"""
    slots: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


class LLMFallbackResolver(Protocol):
    def resolve(
        self,
        *,
        input_text: str,
        normalized_text: str,
        slots: dict[str, Any],
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
    ) -> FallbackSuggestion | None:
        ...


class LLMTemplateSlotResolver(Protocol):
    def resolve_slots(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        current_slots: dict[str, Any],
        missing_slots: list[str],
    ) -> SlotFallbackSuggestion | None:
        ...


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(slots=True)
class OpenAICompatibleTemplateSlotResolver:
    """面向 OpenAI 兼容协议的模板级补参实现。"""
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 5.0

    def resolve_slots(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        current_slots: dict[str, Any],
        missing_slots: list[str],
    ) -> SlotFallbackSuggestion | None:
        """只为目标模板缺失的少量槽位发起一次补参请求。"""
        target_slots = [
            str(slot_name)
            for slot_name in template.llm_slot_extraction.get("slots", missing_slots)
            if str(slot_name)
        ] or [str(slot_name) for slot_name in missing_slots]
        if not target_slots:
            return None
        # 记录真实耗时，后续 benchmark 会直接拿这个字段评估是否值得开兜底。
        start = time.perf_counter()
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract structured slot values for an already matched metric-query template. "
                        "Return a strict JSON object with a single key named slots."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_prompt(
                        input_text=input_text,
                        normalized_text=normalized_text,
                        template=template,
                        current_slots=current_slots,
                        missing_slots=missing_slots,
                        target_slots=target_slots,
                    ),
                },
            ],
            # 要求供应商直接返回 JSON，减少后处理和幻觉解释文本。
            "response_format": {"type": "json_object"},
        }
        raw = self._post_json(payload)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if raw is None:
            return None
        slots_payload = raw.get("slots")
        # 这里只接受 {"slots": {...}} 这一种窄格式，避免把模型自由文本当结果。
        if not isinstance(slots_payload, dict) or not slots_payload:
            return None
        return SlotFallbackSuggestion(
            slots=slots_payload,
            trace={
                "provider": "openai_compatible",
                "model": self.model,
                "target_slots": target_slots,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

    def _build_prompt(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        current_slots: dict[str, Any],
        missing_slots: list[str],
        target_slots: list[str],
    ) -> str:
        """把模板配置和当前缺失槽位收束成一个非常窄的提参任务。"""
        instructions = str(template.llm_slot_extraction.get("instructions", "")).strip()
        slot_hints = self._build_slot_hints(template, target_slots)
        # prompt 里显式给出已知槽位、缺失槽位和 extractor 提示，
        # 让模型做的是“补全”，不是重新理解整道题。
        return (
            f"template_id: {template.template_id}\n"
            f"description: {template.description}\n"
            f"required_slots: {template.required_slots}\n"
            f"optional_slots: {template.optional_slots}\n"
            f"target_slots: {target_slots}\n"
            f"current_slots: {json.dumps(current_slots, ensure_ascii=False)}\n"
            f"missing_slots: {missing_slots}\n"
            f"slot_hints: {json.dumps(slot_hints, ensure_ascii=False)}\n"
            f"input_text: {input_text}\n"
            f"normalized_text: {normalized_text}\n"
            f"template_instructions: {instructions or 'Only fill slots that are clearly supported by the query.'}\n"
            "Return JSON like {\"slots\": {\"slot_name\": value}}. "
            "Do not invent unsupported values. Omit unknown slots."
        )

    def _build_slot_hints(
        self,
        template: TemplateDefinition,
        target_slots: list[str],
    ) -> dict[str, Any]:
        """把模板本地 extractor 转成 LLM 能读懂的提示，减少胡编参数。"""
        hints: dict[str, Any] = {}
        for slot_name in target_slots:
            definition = template.slot_extractors.get(slot_name)
            if definition is None:
                continue
            slot_hint: list[dict[str, Any]] = []
            for extractor in definition.extractors:
                extractor_type = str(extractor.get("type", ""))
                if extractor_type == "keyword_value":
                    # keyword_value 的 cases 可以直接暴露给模型，告诉它允许的离散值范围。
                    slot_hint.append(
                        {
                            "type": "keyword_value",
                            "cases": [
                                {
                                    "terms": list(case.get("terms", [])),
                                    "value": case.get("value"),
                                }
                                for case in extractor.get("cases", [])
                                if isinstance(case, dict)
                            ],
                        }
                    )
                elif extractor_type == "regex":
                    # regex 不能直接强迫模型“跑正则”，但可以把值类型和范围提示给它。
                    slot_hint.append(
                        {
                            "type": "regex",
                            "patterns": [
                                {
                                    "pattern": pattern.get("pattern"),
                                    "value_type": pattern.get("value_type", "string"),
                                    "min": pattern.get("min"),
                                    "max": pattern.get("max"),
                                }
                                for pattern in extractor.get("patterns", [])
                                if isinstance(pattern, dict)
                            ],
                        }
                    )
            if slot_hint:
                hints[slot_name] = slot_hint
        return hints

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """最小化的 HTTP 调用层，只负责拿到 JSON 响应。"""
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except Exception:
            # fallback 失败不应该打断主链路，所以统一吞掉异常并返回 None。
            return None
        try:
            response_payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        content = (
            response_payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict)
            )
        if not isinstance(content, str):
            return None
        content = content.strip()
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 某些兼容实现会在 JSON 前后包一层解释文本，这里做一次兜底提取。
            match = _JSON_BLOCK_RE.search(content)
            if match is None:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
