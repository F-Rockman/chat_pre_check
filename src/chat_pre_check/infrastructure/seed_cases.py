from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = ("case_id", "scene_id", "label", "text")
OPTIONAL_FIELDS = (
    "route_type",
    "slots",
    "tags",
    "priority",
    "owner",
    "version",
    "enabled",
    "risk_level",
    "source",
    "notes",
)


@dataclass(slots=True)
class SeedCaseImportResult:
    """Seed 导入统计结果。"""
    rows_total: int
    rows_ok: int
    rows_invalid: int
    duplicates: int
    output_count: int
    errors: list[dict[str, Any]]


def load_seed_case_rows(input_path: Path, input_format: str = "auto") -> list[dict[str, Any]]:
    """从 CSV/JSON/JSONL 读取原始 seed 行。"""
    fmt = detect_format(input_path, input_format)
    if fmt == "csv":
        return _load_csv_rows(input_path)
    if fmt == "json":
        return _load_json_rows(input_path)
    if fmt == "jsonl":
        return _load_jsonl_rows(input_path)
    raise ValueError(f"Unsupported input format: {fmt}")


def detect_format(input_path: Path, input_format: str) -> str:
    """检测输入文件格式。"""
    if input_format != "auto":
        return input_format
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    if suffix in (".jsonl", ".ndjson"):
        return "jsonl"
    raise ValueError(f"Unable to infer format from suffix: {suffix}")


def import_seed_cases(
    rows: list[dict[str, Any]],
    *,
    known_scene_ids: set[str],
    strict: bool = True,
    allow_unknown_scene: bool = False,
    on_duplicate: str = "error",
) -> tuple[list[dict[str, Any]], SeedCaseImportResult]:
    """校验并归一化 seed 行，返回可入库结果和统计信息。"""
    errors: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    duplicate_count = 0
    seen: dict[str, int] = {}

    for idx, row in enumerate(rows, start=1):
        try:
            item = normalize_seed_case_row(row)
            if not allow_unknown_scene and item["scene_id"] not in known_scene_ids:
                raise ValueError(f"Unknown scene_id: {item['scene_id']}")
            case_id = item["case_id"]
            if case_id in seen:
                duplicate_count += 1
                if on_duplicate == "error":
                    raise ValueError(f"Duplicate case_id: {case_id}")
                if on_duplicate == "keep_first":
                    continue
                if on_duplicate == "keep_last":
                    normalized[seen[case_id]] = item
                    continue
                raise ValueError(f"Unsupported on_duplicate: {on_duplicate}")
            seen[case_id] = len(normalized)
            normalized.append(item)
        except Exception as exc:
            errors.append({"row": idx, "error": str(exc), "data": row})
            if strict:
                raise

    result = SeedCaseImportResult(
        rows_total=len(rows),
        rows_ok=len(normalized),
        rows_invalid=len(errors),
        duplicates=duplicate_count,
        output_count=len(normalized),
        errors=errors,
    )
    return normalized, result


def normalize_seed_case_row(row: dict[str, Any]) -> dict[str, Any]:
    """单行 seed 归一化。"""
    item: dict[str, Any] = {}
    raw = {str(k).strip(): v for k, v in row.items()}

    for field in REQUIRED_FIELDS:
        value = raw.get(field)
        if value is None or str(value).strip() == "":
            raise ValueError(f"Missing required field: {field}")
        item[field] = str(value).strip()

    if len(item["text"]) < 2:
        raise ValueError("text too short")

    item["route_type"] = str(raw.get("route_type", "route_nl2sql")).strip()
    item["enabled"] = _to_bool(raw.get("enabled", True))
    item["priority"] = _to_int(raw.get("priority", 100))
    item["owner"] = str(raw.get("owner", "")).strip()
    item["version"] = str(raw.get("version", "v1")).strip()
    item["risk_level"] = str(raw.get("risk_level", "medium")).strip()
    item["source"] = str(raw.get("source", "import")).strip()
    item["notes"] = str(raw.get("notes", "")).strip()

    slots = raw.get("slots")
    slots_json = raw.get("slots_json")
    if slots is not None and slots != "":
        if isinstance(slots, dict):
            item["slots"] = slots
        else:
            item["slots"] = _parse_json_object(str(slots), field="slots")
    elif slots_json is not None and str(slots_json).strip() != "":
        item["slots"] = _parse_json_object(str(slots_json), field="slots_json")
    else:
        item["slots"] = {}

    tags = raw.get("tags", [])
    if isinstance(tags, list):
        item["tags"] = [str(x).strip() for x in tags if str(x).strip()]
    else:
        item["tags"] = _split_tags(str(tags))

    for field in OPTIONAL_FIELDS:
        item.setdefault(field, _default_for(field))
    return item


def merge_seed_cases(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    mode: str = "replace",
) -> list[dict[str, Any]]:
    """按策略合并旧 seed 与新 seed。"""
    if mode == "replace":
        return sorted(incoming, key=lambda x: x["case_id"])
    if mode == "upsert":
        by_id = {item["case_id"]: item for item in existing}
        for item in incoming:
            by_id[item["case_id"]] = item
        return sorted(by_id.values(), key=lambda x: x["case_id"])
    raise ValueError(f"Unsupported merge mode: {mode}")


def dump_seed_cases(path: Path, cases: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        return [dict(row) for row in reader]


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("JSON input must be a list")
    return [dict(item) for item in data]


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for lineno, line in enumerate(fp, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {lineno}: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError(f"JSONL line {lineno} must be object")
            rows.append(data)
    return rows


def _parse_json_object(text: str, *, field: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        recovered = _try_recover_json_object(text)
        if recovered is None:
            raise ValueError(f"{field} must be valid JSON object") from exc
        data = recovered
    if not isinstance(data, dict):
        raise ValueError(f"{field} must be JSON object")
    return data


def _try_recover_json_object(text: str) -> dict[str, Any] | None:
    candidates = [
        text.replace('\\"', '"'),
        text.replace("“", '"').replace("”", '"'),
        text.strip("'").replace("'", '"'),
    ]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _split_tags(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    text = text.replace(",", "|")
    return [part.strip() for part in text.split("|") if part.strip()]


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off", ""):
        return False
    raise ValueError(f"Invalid bool value: {value}")


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid int value: {value}") from exc


def _default_for(field: str) -> Any:
    if field in ("tags",):
        return []
    if field in ("slots",):
        return {}
    if field == "enabled":
        return True
    if field == "priority":
        return 100
    if field == "route_type":
        return "route_nl2sql"
    if field == "version":
        return "v1"
    if field == "risk_level":
        return "medium"
    if field == "source":
        return "import"
    return ""
