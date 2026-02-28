from __future__ import annotations

from pathlib import Path

from chat_pre_check.infrastructure.seed_cases import (
    import_seed_cases,
    load_seed_case_rows,
    merge_seed_cases,
    normalize_seed_case_row,
)


def test_normalize_seed_case_row_from_csv_shape():
    row = {
        "case_id": "seed_test_1",
        "scene_id": "alarm.query",
        "label": "测试",
        "text": "近24小时核心网告警Top10",
        "slots_json": "{\"topn\":10}",
        "tags": "alarm|topn",
        "enabled": "true",
        "priority": "120",
    }
    item = normalize_seed_case_row(row)
    assert item["case_id"] == "seed_test_1"
    assert item["slots"]["topn"] == 10
    assert item["tags"] == ["alarm", "topn"]
    assert item["enabled"] is True
    assert item["priority"] == 120


def test_import_seed_cases_unknown_scene_non_strict():
    rows = [
        {
            "case_id": "seed_ok",
            "scene_id": "alarm.query",
            "label": "ok",
            "text": "ok text",
        },
        {
            "case_id": "seed_bad_scene",
            "scene_id": "missing.scene",
            "label": "bad",
            "text": "bad text",
        },
    ]
    imported, result = import_seed_cases(
        rows,
        known_scene_ids={"alarm.query"},
        strict=False,
        allow_unknown_scene=False,
        on_duplicate="error",
    )
    assert len(imported) == 1
    assert result.rows_invalid == 1


def test_import_seed_cases_duplicate_keep_last():
    rows = [
        {
            "case_id": "seed_dup",
            "scene_id": "alarm.query",
            "label": "v1",
            "text": "v1",
        },
        {
            "case_id": "seed_dup",
            "scene_id": "alarm.query",
            "label": "v2",
            "text": "v2",
        },
    ]
    imported, result = import_seed_cases(
        rows,
        known_scene_ids={"alarm.query"},
        strict=False,
        allow_unknown_scene=False,
        on_duplicate="keep_last",
    )
    assert len(imported) == 1
    assert imported[0]["label"] == "v2"
    assert result.duplicates == 1


def test_load_seed_case_rows_csv(tmp_path: Path):
    csv_path = tmp_path / "seed.csv"
    csv_path.write_text(
        "case_id,scene_id,label,text\nseed_1,alarm.query,l1,t1\n",
        encoding="utf-8",
    )
    rows = load_seed_case_rows(csv_path, "auto")
    assert rows[0]["case_id"] == "seed_1"


def test_merge_seed_cases_upsert():
    existing = [{"case_id": "a", "scene_id": "alarm.query", "label": "old", "text": "old"}]
    incoming = [{"case_id": "a", "scene_id": "alarm.query", "label": "new", "text": "new"}]
    merged = merge_seed_cases(existing, incoming, mode="upsert")
    assert len(merged) == 1
    assert merged[0]["label"] == "new"
