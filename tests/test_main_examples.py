from __future__ import annotations

from main import DEFAULT_EXAMPLES
from template_capability.engine import TemplateCapabilityEngine


ENGINE = TemplateCapabilityEngine.from_file("configs/templates.json")


def test_default_examples_cover_main_demo_flow():
    assert len(DEFAULT_EXAMPLES) >= 10
    statuses = {item["expected_status"] for item in DEFAULT_EXAMPLES}
    assert statuses == {"matched", "partial", "unmatched"}


def test_default_examples_produce_expected_results():
    for item in DEFAULT_EXAMPLES:
        payload = ENGINE.match(item["text"]).to_dict()
        assert payload["template_id"] == item["expected_template_id"]
        assert payload["status"] == item["expected_status"]
