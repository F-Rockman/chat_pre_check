from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from template_capability.models import SlotExtractorDefinition


PUNCTUATION_RE = re.compile(r"[，。？！!?,:：;；、()\[\]{}<>《》\"'`]+")


def normalize_text(text: str) -> str:
    """只做轻量标准化，不做业务改写。"""
    normalized = unicodedata.normalize("NFKC", text).strip().lower()
    normalized = PUNCTUATION_RE.sub(" ", normalized)
    return " ".join(normalized.split())


class SlotValueExtractor(Protocol):
    def extract(self, text: str) -> Any | None:
        ...


@dataclass(slots=True)
class KeywordValueExtractor:
    cases: list[dict[str, Any]]

    def extract(self, text: str) -> Any | None:
        for case in self.cases:
            terms = [normalize_text(str(term)) for term in case.get("terms", [])]
            if not terms:
                continue
            if any(term and term in text for term in terms):
                return copy.deepcopy(case.get("value"))
        return None


@dataclass(slots=True)
class RegexValueExtractor:
    patterns: list[dict[str, Any]]
    _compiled_patterns: list[tuple[re.Pattern[str], int, str, Any, Any, Any]] = field(
        init=False,
        default_factory=list,
    )

    def __post_init__(self) -> None:
        self._compiled_patterns = [
            (
                re.compile(str(spec["pattern"]), re.IGNORECASE),
                int(spec.get("group", 1)),
                str(spec.get("value_type", "string")),
                spec.get("min"),
                spec.get("max"),
                spec.get("value"),
            )
            for spec in self.patterns
            if "pattern" in spec
        ]

    def extract(self, text: str) -> Any | None:
        for pattern, group, value_type, min_value, max_value, fixed_value in self._compiled_patterns:
            match = pattern.search(text)
            if not match:
                continue
            if fixed_value is not None:
                return copy.deepcopy(fixed_value)
            raw_value = match.group(group)
            value = _cast_value(raw_value, value_type)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                if min_value is not None and value < min_value:
                    continue
                if max_value is not None and value > max_value:
                    continue
            return value
        return None


def build_slot_registry(
    definitions: dict[str, SlotExtractorDefinition],
) -> "SlotExtractorRegistry":
    extractors: dict[str, list[SlotValueExtractor]] = {}
    for slot_name, definition in definitions.items():
        slot_extractors: list[SlotValueExtractor] = []
        for extractor in definition.extractors:
            extractor_type = str(extractor.get("type", "")).lower()
            if extractor_type == "keyword_value":
                slot_extractors.append(
                    KeywordValueExtractor(cases=[dict(case) for case in extractor.get("cases", [])])
                )
                continue
            if extractor_type == "regex":
                slot_extractors.append(
                    RegexValueExtractor(
                        patterns=[dict(pattern) for pattern in extractor.get("patterns", [])]
                    )
                )
        extractors[slot_name] = slot_extractors
    return SlotExtractorRegistry(extractors)


@dataclass(slots=True)
class SlotExtractorRegistry:
    extractors: dict[str, list[SlotValueExtractor]]

    def extract(self, text: str) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        for slot_name, slot_extractors in self.extractors.items():
            for extractor in slot_extractors:
                value = extractor.extract(text)
                if value not in (None, ""):
                    slots[slot_name] = value
                    break
        return slots


def _cast_value(raw_value: str, value_type: str) -> Any | None:
    try:
        if value_type == "int":
            return int(raw_value)
        if value_type == "float":
            return float(raw_value)
        return str(raw_value)
    except ValueError:
        return None
