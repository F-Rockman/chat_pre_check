from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib import request

from template_capability.models import MatchStatus, TemplateCandidate, TemplateDefinition


@dataclass(slots=True)
class FallbackSuggestion:
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
        target_slots = [
            str(slot_name)
            for slot_name in template.llm_slot_extraction.get("slots", missing_slots)
            if str(slot_name)
        ] or [str(slot_name) for slot_name in missing_slots]
        if not target_slots:
            return None
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
            "response_format": {"type": "json_object"},
        }
        raw = self._post_json(payload)
        if raw is None:
            return None
        slots_payload = raw.get("slots")
        if not isinstance(slots_payload, dict) or not slots_payload:
            return None
        return SlotFallbackSuggestion(
            slots=slots_payload,
            trace={
                "provider": "openai_compatible",
                "model": self.model,
                "target_slots": target_slots,
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
        instructions = str(template.llm_slot_extraction.get("instructions", "")).strip()
        return (
            f"template_id: {template.template_id}\n"
            f"description: {template.description}\n"
            f"required_slots: {template.required_slots}\n"
            f"optional_slots: {template.optional_slots}\n"
            f"target_slots: {target_slots}\n"
            f"current_slots: {json.dumps(current_slots, ensure_ascii=False)}\n"
            f"missing_slots: {missing_slots}\n"
            f"input_text: {input_text}\n"
            f"normalized_text: {normalized_text}\n"
            f"template_instructions: {instructions or 'Only fill slots that are clearly supported by the query.'}\n"
            "Return JSON like {\"slots\": {\"slot_name\": value}}. "
            "Do not invent unsupported values. Omit unknown slots."
        )

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
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
            match = _JSON_BLOCK_RE.search(content)
            if match is None:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
