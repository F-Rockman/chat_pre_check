from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from template_capability.models import TemplateDefinition


@dataclass(slots=True)
class TemplateConfig:
    """模板能力运行配置。"""

    match_threshold: float
    weights: dict[str, float]
    templates: list[TemplateDefinition]


def load_template_config(path: str | Path) -> TemplateConfig:
    """从 JSON 文件加载模板配置。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    templates = [
        TemplateDefinition(
            scene_id=str(item["scene_id"]),
            template_id=str(item["template_id"]),
            label=str(item["label"]),
            keywords=[str(token) for token in item.get("keywords", [])],
            negative_keywords=[str(token) for token in item.get("negative_keywords", [])],
            slot_schema={
                "required": [str(token) for token in item.get("slot_schema", {}).get("required", [])],
                "optional": [str(token) for token in item.get("slot_schema", {}).get("optional", [])],
            },
            examples=[str(token) for token in item.get("examples", [])],
        )
        for item in payload.get("templates", [])
    ]
    return TemplateConfig(
        match_threshold=float(payload.get("match_threshold", 0.55)),
        weights={str(key): float(value) for key, value in payload.get("weights", {}).items()},
        templates=templates,
    )

