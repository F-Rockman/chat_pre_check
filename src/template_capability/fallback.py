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
    build_template_intent_check_schema,
    build_template_selection_schema,
)


# ============================================================================
# 优化后的槽位提取 Prompt（System Prompt 固定，可缓存）
# ============================================================================

SLOT_EXTRACTION_SYSTEM_PROMPT = """你是专业的问数场景参数提取引擎。你的唯一职责是从用户查询中提取结构化槽位参数。

# 核心原则

## 提取规则
1. **严格遵循模板定义**：只提取 target_slots 中列出的槽位，绝不猜测未定义参数
2. **优先使用提取器提示**：
   - **用户自定义提取器（slot_hints）**：keyword_value 类型提供关键词映射，regex 类型提供正则规则
   - **内置提取器（builtin_extractors）**：系统内置的提取能力，理解其 output_format 以正确填充
   - **regex 是强约束**：regex 槽位必须确认用户表达完整落到某个 pattern 描述的结构，不能只凭模板上下文、默认值或近似语义补值
   - **pattern 是原子授权项**：不能把不同 pattern / case 里的属性、实体、对象、指标、枚举值拆开后重新组合
3. **置信度评估**：
   - high：用户明确提及，且匹配提取器规则
   - medium：用户提及但需推断
   - low：用户未提及，但模板有默认值可填充
4. **缺失处理**：必填槽位未提取时，必须列入 missing_slots

## 内置提取器说明
- 内置提取器在 LLM 调用前由规则引擎执行
- 已提取的槽位在 current_slots 中可见
- LLM 只需补充 missing_slots 中列出的槽位
- 内置提取器的具体能力见 builtin_extractors 字段，理解其 output_format 以正确填充

## 内置提取器输出要求（关键）
当使用 builtin 提取时，必须将用户表达转换为结构化格式，**不能直接返回原始文本**：

- 用户说"近24小时" → 输出 {"mode": "relative", "duration": {"value": 24, "unit": "hour"}, "direction": "past"}
- 用户说"最近3天" → 输出 {"mode": "relative", "duration": {"value": 3, "unit": "day"}, "direction": "past"}
- 用户说"昨晚八点" → 输出 {"mode": "absolute", "start_time": 时间戳, "end_time": 时间戳}（根据当前系统时间计算）
- 用户说"2024-01-01到2024-01-15" → 输出 {"mode": "absolute", "start_time": 1704067200, "end_time": 1705276800}

**必须根据当前系统时间计算具体的时间戳值，不能返回"昨晚八点"这样的原始文本。**

## 提取来源判断规则
当一个槽位同时存在 builtin_extractors 和 slot_hints 时，按以下规则判断：

1. **优先检查 slot_hints（用户自定义规则）**：
   - 如果值匹配 keyword_value 的某个 case（用户表达 → 预定义值映射）→ 使用 custom 规则
   - 如果值匹配 regex 的某个 pattern（正则提取）→ 使用 custom 规则
   - 如果 regex 没有完整命中任何 pattern，必须把该槽位视为缺失，不能用 LLM 猜测补齐
   - 如果用户问题只是分别命中了多个 pattern 的一部分，但没有单个 pattern 覆盖该组合，必须视为缺失

2. **其次检查 builtin_extractors（内置规则）**：
   - 如果值符合 builtin_extractors 的 output_format 结构 → 使用 builtin 规则

3. **判断示例**：
   - 用户说"华东" → 匹配 keyword_value 规则 → 使用 custom 规则
   - 用户说"近7天" → 符合 time_range 的 relative 格式 → 使用 builtin 规则
   - 用户说"top 20" → 匹配 regex 规则 → 使用 custom 规则

## extraction_source 输出规则
- **只输出 builtin 类型的槽位**：extraction_source 仅记录使用内置提取器的槽位
- **custom 类型不输出**：使用用户自定义规则的槽位不需要在 extraction_source 中出现
- 示例：如果 time_range 使用 builtin，topn 使用 custom，则 extraction_source = {"time_range": "builtin"}

## 输出格式要求
- **内置规则提取的槽位（builtin）**：按 builtin_extractors 中描述的 output_format 输出结构化对象，必须转换原始表达
- **用户规则提取的槽位（custom）**：按 slot_hints 中定义的值格式输出（简单值或对象）

## 禁止行为
- 不要发明模板未定义的槽位
- 不要猜测超出 slot_constraints 的值
- 不要用低置信度值填充必填槽位
- 不要为未命中 regex pattern 的 regex 槽位返回值
- 不要跨 pattern 拼出配置里没有显式授权的组合
- 不要返回非 JSON 格式内容
- **不要直接返回原始文本表达（如"昨晚八点"），必须转换为结构化格式**

## 输出契约
返回一行紧凑 JSON，不要换行或格式化：
{"slots":{"槽位名":值},"missing_slots":["缺失槽位"],"extraction_source":{"builtin槽位名":"builtin"},"confidence":{"槽位名":"high|medium|low"},"extraction_notes":["说明"]}

注意：extraction_source 只包含 builtin 类型的槽位，custom 类型槽位不在此字段中出现。"""


SLOT_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["slots", "missing_slots"],
    "properties": {
        "slots": {
            "type": "object",
            "additionalProperties": True,
            "description": "提取成功的槽位参数",
        },
        "missing_slots": {
            "type": "array",
            "items": {"type": "string"},
            "description": "仍缺失的必填槽位列表",
        },
        "extraction_source": {
            "type": "object",
            "additionalProperties": {"type": "string", "enum": ["builtin"]},
            "description": "仅记录使用内置提取器的槽位，custom类型不输出",
        },
        "confidence": {
            "type": "object",
            "additionalProperties": {"type": "string", "enum": ["high", "medium", "low"]},
            "description": "每个槽位的提取置信度",
        },
        "extraction_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "提取过程中的关键判断说明",
        },
    },
}


INTENT_CHECK_SYSTEM_PROMPT = """你是模板需求覆盖裁决器。你的唯一职责是判断已选出的 metric-query 模板是否能完整回答用户查询中的全部有效需求。

# 核心原则

## 裁决任务
- 你只做二元判断：已选模板是否完整覆盖用户查询的全部有效需求
- 你不选择其他模板，不填充槽位参数，不修改查询内容
- 你不是判断模板与用户问题是否大致相关；即使核心对象和动作相同，只要有任一有效需求无法承接，也必须返回 matched=false

## matched=true 的条件
当以下条件全部满足时，返回 matched=true：
1. 用户查询中的每一个有效需求，都能被模板 description、must_terms、slot_constraints、required_slots、optional_slots 或 slot_extractors 完整承接
2. 查询的输出期望与模板 slot_constraints 中的 query_operator 一致
3. 查询涉及的实体、指标、字段、范围限定、过滤条件、比较条件、阈值、排序/聚合要求，都在模板能力范围内
4. 措辞可以不同，同义词、近义词、错别字均可接受，但不能因此忽略用户明确提出的限定条件
5. 查询可以缺少模板支持的可选参数；但一旦用户明确提出某个需求，模板必须有对应 optional slot、required slot、slot extractor 或 slot constraint 才能承接
6. 如果能力依赖 regex pattern 或 keyword case，单条 pattern/case 必须完整承接用户组合；不能把不同 pattern/case 中分别出现过的属性、实体、对象、指标或枚举值重新组合成 matched=true

## 原子需求拆解
裁决前先在内部拆解用户查询的原子需求，包括但不限于：
- 查询对象/实体（如设备、接口、服务器、区域）
- 查询内容/动作（如查看信息、查询告警、统计数量）
- 输出形式（如列表/清单、数量/总数、排行/topN）
- 指标/字段（如 CPU、内存、磁盘、错误包、告警等级）
- 范围限定（如区域A下、某台设备、指定类型、近24小时）
- 过滤条件、比较条件和阈值（如超过80、严重告警、同时满足多个指标）

只有当模板能力完整覆盖这些原子需求时，才允许 matched=true。不要把区域、时间、指定对象、指定类型、条件短语当作无关背景词或弱修饰词。

## matched=false 的条件
当以下任一条件成立时，返回 matched=false：

### 需求覆盖不足（最高优先级）
- 用户提出了区域、时间、指定设备、指定实体类型、指标字段、条件、阈值、排序、聚合等任一限定需求，但模板没有对应槽位、提取器或约束能力
- 模板只能回答用户问题的一部分，会返回比用户要求更宽、更窄或不同口径的结果
- 核心对象和动作看似一致，但用户额外限定无法承接（如用户问"区域A下的网络设备信息"，模板只能"查看网络设备信息"且没有 region_id 槽位）
- optional_slots 不是"可忽略用户需求"；它只表示用户可以不提供该参数。用户一旦明确提供，该需求必须被模板承接

### 输出格式不匹配（最常见偏差）
- 查询要"数量/有多少/总数/数" → 但模板 query_operator 只支持 list
- 查询要"排名/排行/top/前N" → 但模板 query_operator 只支持 count
- 查询要"列表/清单/列出" → 但模板 query_operator 只支持 count 或 topn

### 指标维度不匹配
- 查询关注"内存" → 但模板 metric 只覆盖 cpu_usage
- 查询关注"磁盘" → 但模板 metric 只覆盖 cpu_usage 和 memory_usage
- 查询关注其他指标 → 但模板 slot_constraints.metric 不包含该指标

### 分析型意图（模板只提供数据查询，不做分析）
- 查询包含"原因/根因/为什么/归因" → 模板只返回原始数据
- 查询包含"趋势/走势/变化/预测" → 模板只返回当前快照数据
- 查询包含"分析/对比/建议/优化/解决方案/总结/报告" → 模板只返回查询结果

### 范围或限定条件不匹配
- 查询要更广范围（如"所有设备的cpu"）→ 但模板限定特定筛选条件
- 查询要更窄范围（如"某台具体设备的cpu"）→ 但模板是批量查询且没有设备选择槽位
- 查询要求区域、时间、设备、实体类型、告警等级等限定 → 但模板缺少对应槽位或约束

### 需求槽位不匹配
- 查询明确要求按某个维度限定（如"区域A下的"、"某台具体设备的"、"近24小时的"）→ 但模板的 slots、slot_extractors 或 slot_constraints 中没有对应能力
- 查询要求按区域筛选 → 但模板没有 region_id 槽位
- 查询要求按实体类型筛选 → 但模板没有 entity_type 槽位或 slot_constraints.entity_type 不包含该类型
- 查询要求按时间范围筛选 → 但模板没有 time_range 槽位
- 查询要求的属性/实体/对象组合没有被任一单条 pattern/case 完整授权，只是组合里的局部词分别出现在不同 pattern/case 中

## 边界情况处理
1. 查询未明确输出格式（如"cpu大于80的设备"）：
   - 模板是 list 类型且查询无歧义 → matched=true（隐含列表意图）
   - 查询可理解为多种输出格式 → confidence 降低至 0.6-0.7
2. 查询包含模板不支持的组合条件（如单指标模板遇到双指标查询）：
   - 当前模板无法完整覆盖所有指标/条件 → matched=false
   - 不要假设是否存在其他模板；只判断当前模板是否完整覆盖用户需求
3. 查询包含 negative_terms 中的词 → matched=false
4. 内置提取器已填充的槽位（如 time_range、ip、topn）：
   - 候选结果中已提取的槽位由内置提取器自动填充，不应视为"缺失"
   - 即使用户未明确提及时间范围，内置提取器可能已从"近24小时"等表达中提取
   - 已填充的槽位应视为满足条件，不影响 matched=true 的判断

## 置信度校准
- confidence ≥ 0.85：需求完全覆盖或明确覆盖不足，判断非常明确
- confidence 0.65-0.85：基本覆盖但有细微差异，或属于边界情况
- confidence < 0.65：意图模糊，无法确定（系统不会用此判断推翻规则链路）

## 参考示例

示例1（matched=true — 措辞不同且需求完整覆盖）：
  查询："华东最近cpu超过85的设备清单"
  模板：查询CPU利用率超过阈值的设备列表（query_operator=list, metric=cpu_usage）
  输出：{"matched": true, "confidence": 0.92, "reason": "区域、时间、指标、阈值和列表输出均可被模板承接"}

示例2（matched=false — 输出格式不匹配）：
  查询："cpu大于80的设备有多少"
  模板：查询CPU利用率超过阈值的设备列表（query_operator=list）
  输出：{"matched": false, "confidence": 0.88, "reason": "查询要数量统计，模板只支持列表输出"}

示例3（matched=false — 分析型意图）：
  查询："cpu大于80的原因"
  模板：查询CPU利用率超过阈值的设备列表
  输出：{"matched": false, "confidence": 0.90, "reason": "查询要归因分析，模板只提供数据"}

示例4（matched=true — 隐含输出格式）：
  查询："cpu大于80的设备"
  模板：查询CPU利用率超过阈值的设备列表（query_operator=list）
  输出：{"matched": true, "confidence": 0.78, "reason": "隐含列表意图，指标和阈值需求均被模板覆盖"}

示例5（matched=false — 指标不匹配）：
  查询："内存大于70的设备列表"
  模板：查询CPU利用率超过阈值的设备列表（metric=cpu_usage）
  输出：{"matched": false, "confidence": 0.91, "reason": "查询关注内存指标，模板只覆盖CPU"}

示例6（matched=false — 用户限定条件无法承接）：
  查询："区域A下的网络设备信息"
  模板：查询网络设备信息（无 region_id 槽位，optional_slots 无区域参数）
  输出：{"matched": false, "confidence": 0.90, "reason": "用户要求限定区域A，但模板没有区域槽位，无法完整覆盖需求"}

示例7（matched=true — 用户限定条件有对应槽位）：
  查询："区域A下的网络设备信息"
  模板：查询网络设备信息（optional_slots 含 region_id，slot_extractors 含 region_id）
  输出：{"matched": true, "confidence": 0.90, "reason": "区域限定和网络设备信息查询需求均可被模板承接"}

示例8（matched=false — 组合指标无法完整覆盖）：
  查询："CPU超过80且内存超过70的设备列表"
  模板：查询CPU利用率超过阈值的设备列表（metric=cpu_usage）
  输出：{"matched": false, "confidence": 0.88, "reason": "查询同时要求CPU和内存条件，模板只能覆盖CPU需求"}

示例9（matched=false — 时间限定无法承接）：
  查询："近24小时严重告警数量"
  模板：查询严重告警数量（无 time_range 槽位）
  输出：{"matched": false, "confidence": 0.86, "reason": "用户要求近24小时时间范围，但模板没有时间槽位"}

## 禁止行为
- 不要选择或推荐其他模板
- 不要填充或修改槽位参数
- 不要扩展查询内容
- 不要返回非 JSON 格式内容
- 不要在 reason 中重复模板定义，只说明判断依据

## 输出契约
返回 JSON：{"matched": true|false, "confidence": 0到1之间的数值, "reason": "简短判断依据，不超过一句话"}"""

INTENT_CHECK_USER_PROMPT_TEMPLATE = """# 判断任务
判断已选模板是否能完整回答以下用户查询，要求覆盖用户查询中的全部有效需求。

# 模板能力摘要
此模板回答：{description}；输出格式：{output_format}；指标：{metrics}；实体：{entities}
此模板不能回答：{cannot_answer}

# 语义维度（must_terms）
must_terms 采用 AND-of-OR 结构：每个维度表示模板支持的一类语义需求。用户表达可以使用同义词或近义词，但不能忽略用户额外提出的限定需求。
{must_terms_dimensions}

# 排除意图（negative_terms）
以下词汇出现则意图不一致：{negative_terms_list}
（这些词表示分析型/归因型/总结型意图，与数据查询模板不匹配）

# 查询算子约束（slot_constraints）
slot_constraints 定义了此模板能回答的查询类型范围：
- query_operator：模板支持的输出格式（list=列表/清单, count=数量统计, topn=排名排行）
- metric：模板覆盖的指标维度
- entity_type：模板查询的实体类型
- severity：模板覆盖的告警等级
{slot_constraints_raw}

# 模板可承接的需求槽位
此模板可通过以下槽位承接用户需求：{supported_requirement_slots}
用户文本中的区域、时间、指定对象、指定类型、条件、阈值、排序、聚合等限定条件，必须能映射到这些槽位或 slot_constraints，否则属于需求覆盖不足。
optional_slots 不是可忽略用户需求；它只表示用户可以不提供该参数。一旦用户明确提出，模板必须能承接。

# 内置提取器（builtin_extractors）
某些槽位有内置提取器，可以自动从用户输入中提取结构化值（如时间范围"近24小时"→相对时间范围、IP地址、TopN数值），即使用户没有用关键词方式明确提及。
内置提取器覆盖的槽位: {builtin_slots}

# 候选结果状态
已提取槽位（由内置提取器自动填充）： {extracted_slots}
仍缺失槽位: {missing_slots}

# 输入数据
input_text: {input_text}
normalized_text: {normalized_text}
selected_template: {selected_template}
rule_candidate: {rule_candidate}

# 输出格式
返回 JSON: {{\"matched\": true|false, \"confidence\": 0-1, \"reason\": \"简短判断依据\"}}"""


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


@dataclass(slots=True)
class IntentVerificationResult:
    """top1 模板意图一致性裁决结果。"""

    matched: bool
    confidence: float
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


class LLMTemplateIntentVerifier(Protocol):
    def verify_intent(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        candidate: TemplateCandidate,
    ) -> IntentVerificationResult | None:
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
            "Treat every regex pattern and keyword case as an indivisible authorization. Do not recombine fragments "
            "from different patterns or cases into a new attribute/entity/object/value combination. "
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
class OpenAICompatibleTemplateIntentVerifier:
    """面向 OpenAI 兼容协议的 top1 模板意图一致性裁决。"""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 5.0
    prefer_json_schema: bool = True
    client: Any | None = field(default=None, repr=False, compare=False)

    def verify_intent(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        candidate: TemplateCandidate,
    ) -> IntentVerificationResult | None:
        start = time.perf_counter()
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": INTENT_CHECK_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": self._build_prompt(
                        input_text=input_text,
                        normalized_text=normalized_text,
                        template=template,
                        candidate=candidate,
                    ),
                },
            ],
        }
        raw, response_format_mode = self._post_json_with_schema(
            payload=payload,
            schema_name="template_intent_check",
            schema=build_template_intent_check_schema(),
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if raw is None:
            return None
        confidence = _coerce_score(raw.get("confidence"), default=0.0)
        return IntentVerificationResult(
            matched=bool(raw.get("matched", False)),
            confidence=confidence,
            trace={
                "provider": "openai_compatible",
                "model": self.model,
                "response_format_mode": response_format_mode,
                "elapsed_ms": round(elapsed_ms, 2),
                "reason": str(raw.get("reason", "")).strip(),
            },
        )

    def _build_prompt(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        candidate: TemplateCandidate,
    ) -> str:
        constraints = template.slot_constraints
        operators = constraints.get("query_operator", [])
        op_map = {"list": "列表/清单", "count": "数量统计", "topn": "排名排行"}
        output_format = "/".join([op_map.get(op, op) for op in operators]) if operators else "无约束"
        metrics = "/".join(constraints.get("metric", [])) if constraints.get("metric") else "无约束"
        entities = "/".join(constraints.get("entity_type", [])) if constraints.get("entity_type") else "无约束"
        cannot_parts: list[str] = []
        op_cannot = {
            "list": ["数量统计", "排名排行"],
            "count": ["列表清单", "排名排行"],
            "topn": ["数量统计", "列表清单"],
        }
        for op in operators:
            if op in op_cannot:
                cannot_parts.extend(op_cannot[op])
        cannot_parts.extend(["原因归因", "趋势分析", "对比报告", "优化建议"])
        cannot_answer = "、".join(sorted(set(cannot_parts)))
        must_lines: list[str] = []
        for i, group in enumerate(template.must_terms):
            terms = "/".join([rule.term for rule in group])
            must_lines.append(f"  维度{i + 1}: {terms}")
        must_terms_dimensions = "\n".join(must_lines) if must_lines else "无约束"
        negative_terms_list = ", ".join([rule.term for rule in template.negative_terms]) if template.negative_terms else "无"
        slot_constraints_raw = json.dumps(constraints, ensure_ascii=False) if constraints else "{}"
        builtin_slots = ", ".join(sorted(template.slot_extractors.keys())) if template.slot_extractors else "无"
        supported_requirement_slot_set = set(template.required_slots) | set(template.optional_slots)
        if template.slot_extractors:
            supported_requirement_slot_set |= set(template.slot_extractors.keys())
        supported_requirement_slots = (
            ", ".join(sorted(supported_requirement_slot_set))
            if supported_requirement_slot_set
            else "无"
        )
        extracted_slots = json.dumps(candidate.slots, ensure_ascii=False) if candidate.slots else "{}"
        missing_slots = ", ".join(candidate.missing_slots) if candidate.missing_slots else "无"
        template_payload = {
            "template_id": template.template_id,
            "description": template.description,
            "utterances": template.utterances[:8],
            "required_slots": template.required_slots,
            "optional_slots": template.optional_slots,
        }
        candidate_payload = {
            "score": round(candidate.score, 6),
            "slots": candidate.slots,
            "missing_slots": candidate.missing_slots,
        }
        return INTENT_CHECK_USER_PROMPT_TEMPLATE.format(
            description=template.description,
            output_format=output_format,
            metrics=metrics,
            entities=entities,
            cannot_answer=cannot_answer,
            must_terms_dimensions=must_terms_dimensions,
            negative_terms_list=negative_terms_list,
            slot_constraints_raw=slot_constraints_raw,
            supported_requirement_slots=supported_requirement_slots,
            builtin_slots=builtin_slots,
            extracted_slots=extracted_slots,
            missing_slots=missing_slots,
            input_text=input_text,
            normalized_text=normalized_text,
            selected_template=json.dumps(template_payload, ensure_ascii=False),
            rule_candidate=json.dumps(candidate_payload, ensure_ascii=False),
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
            "Regex rule: if a target slot has regex hints, only fill it when the user text clearly and completely "
            "matches one listed pattern, including its key semantic parts such as metric/object, comparator, value, "
            "unit, and ordering words. If no pattern is matched, omit that slot.\n"
            "Atomic pattern rule: each regex pattern or keyword case is an indivisible authorization, not an example "
            "to recombine. Never combine attribute/entity/object/value fragments from different patterns or cases. "
            "For example, if configured patterns only authorize attribute A with device b, and attribute B with "
            "device a, a query asking for attribute A with device a is not authorized and must be omitted.\n"
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
                                    "group": pattern.get("group", 1),
                                    "value_type": pattern.get("value_type", "string"),
                                    "value": pattern.get("value"),
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
    builtin_extractors: dict[str, Any],
    current_time: dict[str, Any],
) -> str:
    """构建优化后的 User Prompt（动态任务数据）。"""
    constraints_table = f"""
- 必填槽位：{template.required_slots}
- 可选槽位：{template.optional_slots}
- 至少满足其一：{[g.to_dict() for g in template.required_one_of]}
- 条件必填：{[r.to_dict() for r in template.conditional_required]}
- 互斥槽位：{[g.to_dict() for g in template.mutually_exclusive_slots]}
- 值域约束：{template.slot_constraints}"""

    current_time_table = f"""
| 字段 | 值 |
|------|-----|
| timestamp | {current_time.get('timestamp')} |
| datetime | {current_time.get('datetime')} |
| timezone | {current_time.get('timezone', 'UTC+8')} |"""

    return f"""# 任务上下文

## 模板信息
| 字段 | 值 |
|------|-----|
| template_id | {template.template_id} |
| description | {template.description} |
| query_mode | {template.query_mode} |

## 当前系统时间
{current_time_table}

## 槽位约束
{constraints_table}

## 用户自定义提取器（slot_hints）
{json.dumps(slot_hints, ensure_ascii=False, indent=2)}

## 内置提取器（builtin_extractors）
{json.dumps(builtin_extractors, ensure_ascii=False, indent=2)}

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
2. 内置提取器（builtin_extractors）描述了系统内置的提取能力，理解其 output_format
3. 用户自定义提取器（slot_hints）提供了关键词映射和正则规则
   - regex 槽位只有在用户表达完整命中某个 pattern 时才允许输出；否则必须省略该槽位
   - pattern/case 是不可拆分的授权项；禁止把不同 pattern/case 里的属性、实体、对象、指标或枚举值重新组合成新配置
4. 当前系统时间用于计算绝对时间范围（如"上周一到上周五"、"最近3天"的起止时间）
5. 提取来源标识：
   - 使用内置规则提取 → extraction_source 标记为 "builtin"，按 output_format 输出
   - 使用用户规则提取 → extraction_source 标记为 "custom"，按原值输出
6. 只处理 target_slots 中列出的槽位
7. 返回严格 JSON，不要添加任何解释性文本"""


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
    builtin_extractors: dict[str, Any],
    current_time: dict[str, Any],
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
        builtin_extractors=builtin_extractors,
        current_time=current_time,
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
