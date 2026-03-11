from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionType(str, Enum):
    """独立模板工程只需要三类出口。"""

    ROUTE_TEMPLATE = "route_template"
    CLARIFY = "clarify"
    REFUSE = "refuse"


@dataclass(slots=True)
class ActionOption:
    """返回给调用方的补参或替代建议。"""

    label: str
    preset_slots: dict[str, Any] = field(default_factory=dict)
    slot_value: Any | None = None


@dataclass(slots=True)
class TemplateDefinition:
    """模板定义，来自外部 JSON 配置。"""

    scene_id: str
    template_id: str
    label: str
    keywords: list[str]
    negative_keywords: list[str]
    slot_schema: dict[str, list[str]]
    examples: list[str]


@dataclass(slots=True)
class RouteDecision:
    """模板引擎输出。"""

    type: DecisionType
    message: str
    scene: str | None = None
    template_id: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    options: list[ActionOption] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "message": self.message,
            "scene": self.scene,
            "template_id": self.template_id,
            "slots": self.slots,
            "missing_slots": self.missing_slots,
            "options": [
                {
                    "label": item.label,
                    "preset_slots": item.preset_slots,
                    "slot_value": item.slot_value,
                }
                for item in self.options
            ],
            "trace": self.trace,
        }

