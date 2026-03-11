from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from template_capability.engine import TemplateCapabilityEngine


ENGINE = TemplateCapabilityEngine.from_file("configs/templates.json")
FIXTURE_PATH = Path("tests/fixtures/evaluation_cases.json")


@lru_cache(maxsize=1)
def load_cases() -> dict[str, list[dict[str, str]]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("text", "template_id"),
    [
        (item["text"], item["template_id"])
        for item in load_cases()["matched"]
    ],
)
def test_evaluation_corpus_matched(text: str, template_id: str):
    payload = ENGINE.match(text).to_dict()
    assert payload["template_id"] == template_id
    assert payload["status"] == "matched"


@pytest.mark.parametrize(
    ("text", "template_id"),
    [
        (item["text"], item["template_id"])
        for item in load_cases()["partial"]
    ],
)
def test_evaluation_corpus_partial(text: str, template_id: str):
    payload = ENGINE.match(text).to_dict()
    assert payload["template_id"] == template_id
    assert payload["status"] == "partial"
    assert payload["missing_slots"]


@pytest.mark.parametrize(
    "text",
    [item["text"] for item in load_cases()["unmatched"]],
)
def test_evaluation_corpus_unmatched(text: str):
    payload = ENGINE.match(text).to_dict()
    assert payload["template_id"] == -1
    assert payload["status"] == "unmatched"


@pytest.mark.parametrize(
    "text",
    [item["text"] for item in load_cases()["not_full_match"]],
)
def test_vague_queries_do_not_become_full_matches(text: str):
    payload = ENGINE.match(text).to_dict()
    assert payload["status"] != "matched"
