from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from template_capability.models import MatchStatus, TemplateCandidate, TemplateDefinition
from template_capability.openai_client import (
    build_openai_client,
    extract_chat_completion_content,
    parse_json_content,
)
from template_capability.structured_output import (
    build_json_object_response_format,
    build_json_schema_response_format,
    build_slot_fill_schema,
    build_template_selection_schema,
)


# ============================================================================
# 优化后的槽位提取 Prompt（System Prompt 固定，可缓存）
# ============================================================================

SLOT_EXTRACTION_SYSTEM_PROMPT = """你是专业的问数场景参数提取引擎。你的唯一职责是从用户查询中提取结构化槽位参数。

# 核心原则

## 提取规则
1. **严格遵循模板定义**：只提取 target_slots 中列出的槽位，绝不猜测未定义参数
2. **优先使用 slot_hints**：
   - keyword_value 类型：用户说"近24小时" → 映射到预设值 {"mode": "relative", "preset": "last_24h"}
   - regex 类型：按正则模式提取，注意 value_type、min、max 约束
3. **置信度评估**：
   - high：用户明确提及，且匹配 slot_hints 规则
   - medium：用户提及但需推断
   - low：用户未提及，但模板有默认值可填充
4. **缺失处理**：必填槽位未提取时，必须列入 missing_slots

## 禁止行为
- 不要发明模板未定义的槽位
- 不要猜测超出 slot_constraints 的值
- 不要用低置信度值填充必填槽位
- 不要返回非 JSON 格式内容

## 输出契约
返回严格 JSON：{"slots": {...}, "missing_slots": [...], "confidence": {...}, "extraction_notes": [...]}"""


SLOT_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["slots", "missing_slots"],
    "properties": {
        "slots": {"type": "object", "additionalProperties": True},
        "missing_slots": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "object",
            "additionalProperties": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "extraction_notes": {"type": "array", "items": {"type": "string"}},
    },
}


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


@dataclass(slots=True)
class OpenAICompatibleFallbackResolver:
    """面向 OpenAI 兼容协议的模板选择级 fallback。

    它不做全模板推理，只在当前 top candidates 里做裁决，或者明确返回 `-1`。
    """

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 5.0
    prefer_json_schema: bool = True
    client: Any | None = field(default=None, repr=False, compare=False)

    def resolve(
        self,
        *,
        input_text: str,
        normalized_text: str,
        slots: dict[str, Any],
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
    ) -> FallbackSuggestion | None:
        if not candidates:
            return None
        candidate_ids = [candidate.template_id for candidate in candidates]
        start = time.perf_counter()
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You arbitrate between a small set of candidate metric-query templates. "
                        "Only choose one of the provided candidate template ids, or return -1 when none is reliable."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_prompt(
                        input_text=input_text,
                        normalized_text=normalized_text,
                        slots=slots,
                        candidates=candidates,
                        templates=templates,
                    ),
                },
            ],
        }
        raw, response_format_mode = self._post_json_with_schema(
            payload=payload,
            schema_name="template_selection_fallback",
            schema=build_template_selection_schema(candidate_ids),
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if raw is None:
            return None
        return self._coerce_selection(
            raw,
            candidates=candidates,
            templates=templates,
            elapsed_ms=elapsed_ms,
            response_format_mode=response_format_mode,
        )

    def _build_prompt(
        self,
        *,
        input_text: str,
        normalized_text: str,
        slots: dict[str, Any],
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
    ) -> str:
        candidate_payload = []
        for candidate in candidates:
            template = templates[candidate.template_id]
            candidate_payload.append(
                {
                    "template_id": candidate.template_id,
                    "description": template.description,
                    "utterances": template.utterances[:5],
                    "required_slots": template.required_slots,
                    "required_one_of": [group.to_dict() for group in template.required_one_of],
                    "conditional_required": [rule.to_dict() for rule in template.conditional_required],
                    "mutually_exclusive_slots": [group.to_dict() for group in template.mutually_exclusive_slots],
                    "must_terms": [[rule.term for rule in group] for group in template.must_terms],
                    "negative_terms": [rule.term for rule in template.negative_terms],
                    "slot_constraints": template.slot_constraints,
                    "current_slots": candidate.slots,
                    "missing_slots": candidate.missing_slots,
                    "base_score": round(candidate.score, 6),
                    "candidate_trace": candidate.trace,
                }
            )
        return (
            f"input_text: {input_text}\n"
            f"normalized_text: {normalized_text}\n"
            f"global_slots: {json.dumps(slots, ensure_ascii=False)}\n"
            f"candidates: {json.dumps(candidate_payload, ensure_ascii=False)}\n"
            "Choose the candidate that best explains the query constraints, or return -1 if none is reliable. "
            "If a candidate is already right but misses one or two obvious values, you may fill those missing slots. "
            "Do not invent a template id that is not listed."
        )

    def _coerce_selection(
        self,
        raw: dict[str, Any],
        *,
        candidates: list[TemplateCandidate],
        templates: dict[str, TemplateDefinition],
        elapsed_ms: float,
        response_format_mode: str,
    ) -> FallbackSuggestion | None:
        candidate_map = {candidate.template_id: candidate for candidate in candidates}
        template_token = str(raw.get("template_id", "")).strip()
        if not template_token:
            return None
        reason = str(raw.get("reason", "")).strip()
        if template_token == "-1":
            return FallbackSuggestion(
                template_id=-1,
                status=MatchStatus.UNMATCHED,
                score=0.0,
                query_mode=None,
                trace={
                    "provider": "openai_compatible",
                    "model": self.model,
                    "response_format_mode": response_format_mode,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "reason": reason,
                },
            )

        candidate = candidate_map.get(template_token)
        template = templates.get(template_token)
        if candidate is None or template is None:
            return None

        supplemental_slots = raw.get("slots")
        merged_slots = _merge_missing_slots_only(candidate.slots, supplemental_slots if isinstance(supplemental_slots, dict) else {})
        raw_missing_slots = raw.get("missing_slots")
        if isinstance(raw_missing_slots, list):
            missing_slots = [str(slot_name) for slot_name in raw_missing_slots if str(slot_name).strip()]
        else:
            missing_slots = list(candidate.missing_slots)

        raw_status = str(raw.get("status", "")).strip().lower()
        if raw_status == MatchStatus.UNMATCHED.value:
            status = MatchStatus.UNMATCHED
        elif raw_status == MatchStatus.MATCHED.value:
            status = MatchStatus.MATCHED
        elif raw_status == MatchStatus.PARTIAL.value:
            status = MatchStatus.PARTIAL
        else:
            status = MatchStatus.PARTIAL if missing_slots else MatchStatus.MATCHED

        score = _coerce_score(raw.get("score"), default=candidate.score)
        return FallbackSuggestion(
            template_id=template.template_id,
            status=status,
            score=score,
            query_mode=template.query_mode,
            slots=merged_slots,
            missing_slots=missing_slots,
            metadata=template.metadata,
            trace={
                "provider": "openai_compatible",
                "model": self.model,
                "response_format_mode": response_format_mode,
                "elapsed_ms": round(elapsed_ms, 2),
                "reason": reason,
            },
        )

    def _post_json_with_schema(
        self,
        *,
        payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        if self.prefer_json_schema:
            json_schema_payload = dict(payload)
            json_schema_payload["response_format"] = build_json_schema_response_format(name=schema_name, schema=schema)
            parsed = self._post_json(json_schema_payload)
            if parsed is not None:
                return parsed, "json_schema"
        json_object_payload = dict(payload)
        json_object_payload["response_format"] = build_json_object_response_format()
        return self._post_json(json_object_payload), "json_object"

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            client = self.client or build_openai_client(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
            )
            response = client.chat.completions.create(**payload)
        except Exception:
            return None
        return parse_json_content(extract_chat_completion_content(response))


@dataclass(slots=True)
class OpenAICompatibleTemplateSlotResolver:
    """面向 OpenAI 兼容协议的模板级补参实现。"""
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 5.0
    prefer_json_schema: bool = True
    client: Any | None = field(default=None, repr=False, compare=False)

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
        }
        raw, response_format_mode = self._post_json_with_schema(
            payload=payload,
            schema_name="template_slot_fill",
            schema=build_slot_fill_schema(template, target_slots),
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if raw is None:
            return None
        slots_payload = self._coerce_slots_payload(raw.get("slots"), target_slots)
        # 这里只接受 {"slots": {...}} 这一种窄格式，避免把模型自由文本当结果。
        if not slots_payload:
            return None
        return SlotFallbackSuggestion(
            slots=slots_payload,
            trace={
                "provider": "openai_compatible",
                "model": self.model,
                "target_slots": target_slots,
                "response_format_mode": response_format_mode,
                "reason": str(raw.get("reason", "")).strip(),
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
            f"required_one_of: {[group.to_dict() for group in template.required_one_of]}\n"
            f"conditional_required: {[rule.to_dict() for rule in template.conditional_required]}\n"
            f"mutually_exclusive_slots: {[group.to_dict() for group in template.mutually_exclusive_slots]}\n"
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

    def _coerce_slots_payload(
        self,
        raw_slots: Any,
        target_slots: list[str],
    ) -> dict[str, Any]:
        if not isinstance(raw_slots, dict):
            return {}
        allowed = set(target_slots)
        return {
            str(slot_name): value
            for slot_name, value in raw_slots.items()
            if str(slot_name) in allowed and value is not None
        }

    def _post_json_with_schema(
        self,
        *,
        payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        if self.prefer_json_schema:
            json_schema_payload = dict(payload)
            json_schema_payload["response_format"] = build_json_schema_response_format(name=schema_name, schema=schema)
            parsed = self._post_json(json_schema_payload)
            if parsed is not None:
                return parsed, "json_schema"
        json_object_payload = dict(payload)
        json_object_payload["response_format"] = build_json_object_response_format()
        return self._post_json(json_object_payload), "json_object"

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """用 openai 客户端发起 chat completion，并解析成 JSON。"""
        try:
            client = self.client or build_openai_client(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
            )
            response = client.chat.completions.create(**payload)
        except Exception:
            # fallback 失败不应该打断主链路，所以统一吞掉异常并返回 None。
            return None
        return parse_json_content(extract_chat_completion_content(response))


def _merge_missing_slots_only(base_slots: dict[str, Any], supplemental_slots: dict[str, Any]) -> dict[str, Any]:
    """LLM 只补充缺失值，不覆盖规则链路已经稳定产出的槽位。"""
    merged = dict(base_slots)
    for slot_name, value in supplemental_slots.items():
        if slot_name not in merged or merged.get(slot_name) in (None, ""):
            merged[slot_name] = value
    return merged


def _coerce_score(raw_value: Any, *, default: float) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


# ============================================================================
# 优化后的槽位提取函数（使用结构化 Prompt）
# ============================================================================


def build_optimized_slot_extraction_prompt(
    template: TemplateDefinition,
    input_text: str,
    normalized_text: str,
    current_slots: dict[str, Any],
    missing_slots: list[str],
    target_slots: list[str],
    slot_hints: dict[str, Any],
) -> str:
    """构建优化后的 User Prompt（动态任务数据）。"""
    constraints_table = f"""
- 必填槽位：{template.required_slots}
- 可选槽位：{template.optional_slots}
- 至少满足其一：{[g.to_dict() for g in template.required_one_of]}
- 条件必填：{[r.to_dict() for r in template.conditional_required]}
- 互斥槽位：{[g.to_dict() for g in template.mutually_exclusive_slots]}
- 值域约束：{template.slot_constraints}"""

    return f"""# 任务上下文

## 模板信息
| 字段 | 值 |
|------|-----|
| template_id | {template.template_id} |
| description | {template.description} |
| query_mode | {template.query_mode} |

## 槽位约束
{constraints_table}

## 槽位提取提示（slot_hints）
{json.dumps(slot_hints, ensure_ascii=False, indent=2)}

## 已提取槽位（规则引擎产出）
{json.dumps(current_slots, ensure_ascii=False, indent=2)}

## 待补充槽位
{missing_slots}

---

# 用户输入

## 原始文本
{input_text}

## 标准化文本
{normalized_text}

---

# 提取任务

请基于上述模板定义和用户输入，提取 {target_slots} 中的槽位参数。

注意：
1. 已提取槽位（current_slots）由规则引擎产出，优先信任，LLM 只补充缺失部分
2. 只处理 target_slots 中列出的槽位
3. 返回严格 JSON，不要添加任何解释性文本"""


def call_llm_for_optimized_slot_extraction(
    client: Any,
    model: str,
    template: TemplateDefinition,
    input_text: str,
    normalized_text: str,
    current_slots: dict[str, Any],
    missing_slots: list[str],
    target_slots: list[str],
    slot_hints: dict[str, Any],
) -> dict[str, Any] | None:
    """调用 LLM 进行槽位提取（使用优化后的结构化 Prompt）。"""
    user_prompt = build_optimized_slot_extraction_prompt(
        template=template,
        input_text=input_text,
        normalized_text=normalized_text,
        current_slots=current_slots,
        missing_slots=missing_slots,
        target_slots=target_slots,
        slot_hints=slot_hints,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": SLOT_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "slot_extraction",
                    "strict": True,
                    "schema": SLOT_EXTRACTION_SCHEMA,
                },
            },
        )
        content = extract_chat_completion_content(response)
        return parse_json_content(content)
    except Exception:
        return None
