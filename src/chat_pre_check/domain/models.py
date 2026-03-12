from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason


@dataclass(slots=True)
class TimeRangeSpec:
    """时间范围标准结构，供规则抽取、模板命中和下游执行共享。"""

    mode: str = "relative"
    preset: str | None = None
    timezone: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    granularity: str | None = None
    anchor_ms: int | None = None
    original_text: str | None = None
    normalized_text: str | None = None
    confidence: float = 0.0


@dataclass(slots=True)
class Candidate:
    """实体候选，如设备、地域等解析结果。"""

    entity_id: str
    name: str
    score: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchHit:
    """检索召回结果的统一表示。"""

    doc_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionOption:
    """返回给前端/调用方的下一步可操作建议。"""

    label: str
    intent: str | None = None
    preset_slots: dict[str, Any] = field(default_factory=dict)
    need_followup_slots: list[str] = field(default_factory=list)
    slot_value: Any | None = None


@dataclass(slots=True)
class TraceStep:
    """单个中间件的观测事件。"""

    step: str
    decision: str
    reason: str
    latency_ms: float
    score: float | None = None
    topk: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TraceCollector:
    """请求级 trace 容器，串联整条路由链路的观测信息。"""

    request_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps: list[TraceStep] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: TraceStep) -> None:
        self.steps.append(step)


@dataclass(slots=True)
class RouteRequest:
    """外部接口输入的标准请求结构。"""

    input_text: str
    context: dict[str, Any] = field(default_factory=dict)
    tenant_id: str | None = None
    role: str | None = None
    trace_level: str = "compact"


@dataclass(slots=True)
class RequestContext:
    """内部运行态上下文，所有中间件通过它共享状态。"""

    input_text: str
    norm_text: str = ""
    tenant_id: str | None = None
    role: str | None = None
    context_scene: str | None = None
    context_flow_type: str | None = None
    route_override: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    entities: dict[str, Any] = field(default_factory=dict)
    scene: str | None = None
    flow_type: str | None = None
    clarify_round: int = 0
    max_clarify_round: int = 5
    pending_slots: list[str] = field(default_factory=list)
    llm_calls: int = 0
    trace_level: str = "compact"
    trace: TraceCollector = field(default_factory=TraceCollector)


@dataclass(slots=True)
class RouteDecision:
    """最终路由结果；所有出口统一收敛到这个结构。"""

    type: DecisionType
    message: str
    scene: str | None = None
    flow_type: str | None = None
    template_id: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    options: list[ActionOption] = field(default_factory=list)
    out_of_scope_reason: OutOfScopeReason | None = None
    clarify_round: int | None = None
    max_clarify_round: int | None = None
    next_action: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # 对外统一转成可序列化结构，避免上层依赖 dataclass 细节。
        return {
            "type": self.type.value,
            "message": self.message,
            "scene": self.scene,
            "flow_type": self.flow_type,
            "template_id": self.template_id,
            "slots": self.slots,
            "missing_slots": self.missing_slots,
            "options": [
                {
                    "label": o.label,
                    "intent": o.intent,
                    "preset_slots": o.preset_slots,
                    "need_followup_slots": o.need_followup_slots,
                    "slot_value": o.slot_value,
                }
                for o in self.options
            ],
            "out_of_scope_reason": (
                self.out_of_scope_reason.value if self.out_of_scope_reason else None
            ),
            "clarify_round": self.clarify_round,
            "max_clarify_round": self.max_clarify_round,
            "next_action": self.next_action,
            "trace": self.trace,
        }
