from __future__ import annotations

import json
import shutil
from pathlib import Path

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.domain.models import RouteRequest
from chat_pre_check.infrastructure.extractors.ac_prefill import ACSlotPrefiller, PrefillTerm
from tests.fixtures.fakes import FakeVectorRetriever


class _FailingResolver:
    def resolve(self, text: str, topk: int = 5):
        raise RuntimeError("resolver down")


def _build_temp_config(
    tmp_path: Path,
    *,
    terms: list[dict],
    auto_commit: bool = True,
) -> Path:
    src = Path("configs")
    dst = tmp_path / "configs"
    shutil.copytree(src, dst)

    vector_file = dst / "vector.json"
    vector_cfg = json.loads(vector_file.read_text(encoding="utf-8"))
    vector_cfg["param_prefill"] = {
        "enabled": True,
        "dictionary_file": "ac_terms.json",
        "auto_commit": auto_commit,
        "commit_score": 0.95,
        "min_gap": 0.05,
        "max_candidates_per_slot": 3,
        "skip_remote_resolver_when_prefilled": True,
    }
    vector_file.write_text(json.dumps(vector_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    (dst / "ac_terms.json").write_text(
        json.dumps(terms, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dst


def test_ac_slot_prefiller_prefers_longer_higher_score_match() -> None:
    prefiller = ACSlotPrefiller(
        [
            PrefillTerm(term="华", slot="region_id", value="region_cn", score=0.4),
            PrefillTerm(term="华东", slot="region_id", value="east_cn", score=0.9),
            PrefillTerm(term="华东区", slot="region_id", value="east_cn", score=0.95),
        ]
    )
    result = prefiller.match("查询华东区离线设备")
    assert "region_id" in result.slot_matches
    assert result.slot_matches["region_id"][0].resolved_slot_value() == "east_cn"
    assert result.slot_candidates["region_id"][0].entity_id == "east_cn"


def test_prefill_allows_route_when_resolver_unavailable(tmp_path: Path) -> None:
    cfg_dir = _build_temp_config(
        tmp_path,
        terms=[
            {
                "term": "华东",
                "slot": "region_id",
                "value": "east_cn",
                "entity_id": "east_cn",
                "entity_name": "华东",
                "score": 0.99,
            }
        ],
        auto_commit=True,
    )
    engine = build_engine(
        config_dir=str(cfg_dir),
        retriever_override=FakeVectorRetriever(),
        device_resolver_override=_FailingResolver(),
        region_resolver_override=_FailingResolver(),
    )
    decision = engine.route(RouteRequest(input_text="昨天华东离线设备数"))
    payload = decision.to_dict()
    assert payload["type"] == "route_template"
    assert payload["template_id"] == "tpl_device_offline_count"
    assert payload["slots"]["region_id"] == "east_cn"


def test_prefill_candidates_support_clarify_options(tmp_path: Path) -> None:
    cfg_dir = _build_temp_config(
        tmp_path,
        terms=[
            {
                "term": "华东",
                "slot": "region_id",
                "value": "east_cn",
                "entity_id": "east_cn",
                "entity_name": "华东",
                "score": 0.6,
            }
        ],
        auto_commit=False,
    )
    engine = build_engine(
        config_dir=str(cfg_dir),
        retriever_override=FakeVectorRetriever(),
        device_resolver_override=_FailingResolver(),
        region_resolver_override=_FailingResolver(),
    )
    decision = engine.route(RouteRequest(input_text="近24小时华东离线设备数量"))
    payload = decision.to_dict()
    assert payload["type"] == "clarify"
    assert "region_id" in payload["missing_slots"]
    labels = [item["label"] for item in payload["options"]]
    assert "华东" in labels
