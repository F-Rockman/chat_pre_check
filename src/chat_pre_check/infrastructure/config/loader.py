from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chat_pre_check.infrastructure.config.validator import validate_config


@dataclass(slots=True)
class AppConfig:
    scenes: list[dict[str, Any]]
    templates: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    rules: dict[str, Any]
    thresholds: dict[str, float]
    vector: dict[str, Any]
    slot_policies: dict[str, Any]


def _load_json_optional(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return _load_json(path)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_app_config(config_dir: str | Path) -> AppConfig:
    root = Path(config_dir)
    config = AppConfig(
        scenes=_load_json(root / "scenes.json"),
        templates=_load_json(root / "templates.json"),
        cases=_load_json(root / "cases.json"),
        rules=_load_json(root / "rules.json"),
        thresholds=_load_json(root / "thresholds.json"),
        vector=_load_json(root / "vector.json"),
        slot_policies=_load_json_optional(root / "slot_policies.json", default={}),
    )
    validate_config(config)
    return config
