from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RouteRequestDTO(BaseModel):
    input_text: str
    context: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str | None = None
    role: str | None = None
    trace_level: str = "compact"


class ActionOptionDTO(BaseModel):
    label: str
    intent: str | None = None
    preset_slots: dict[str, Any] = Field(default_factory=dict)
    need_followup_slots: list[str] = Field(default_factory=list)
    slot_value: Any | None = None


class RouteResponseDTO(BaseModel):
    type: str
    message: str
    scene: str | None = None
    template_id: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    options: list[ActionOptionDTO] = Field(default_factory=list)
    out_of_scope_reason: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)
