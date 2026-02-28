from __future__ import annotations

import json
import shutil
from pathlib import Path

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.domain.models import RouteRequest, SearchHit
from tests.fixtures.fakes import FakeDeviceResolver, FakeRegionResolver


class _SeedScopeRetriever:
    def __init__(self, seed_score: float) -> None:
        self.seed_score = seed_score

    def search_scene(self, query_text: str, topk: int = 5):
        return [SearchHit("scene_alarm_analysis", 0.95, {"scene_id": "alarm.analysis"})]

    def search_template(self, scene_id: str, query_text: str, topk: int = 5):
        return []

    def search_seed_cases(self, query_text: str, topk: int = 5):
        return [
            SearchHit(
                "seed_case_x",
                self.seed_score,
                {
                    "case_id": "seed_alarm_ticket_rate",
                    "scene_id": "alarm.analysis",
                    "label": "统计近7天每个地市告警与工单关联率",
                },
            )
        ]


def _build_temp_config(tmp_path: Path, enable_guard: bool, min_score: float) -> Path:
    src = Path("configs")
    dst = tmp_path / "configs"
    shutil.copytree(src, dst)
    vector_file = dst / "vector.json"
    data = json.loads(vector_file.read_text(encoding="utf-8"))
    data["seed_scope_guard"]["enabled"] = enable_guard
    data["seed_scope_guard"]["min_score"] = min_score
    vector_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def test_seed_scope_guard_disabled_allows_route(tmp_path):
    cfg_dir = _build_temp_config(tmp_path, enable_guard=False, min_score=0.95)
    engine = build_engine(
        config_dir=str(cfg_dir),
        retriever_override=_SeedScopeRetriever(seed_score=0.1),
        device_resolver_override=FakeDeviceResolver(),
        region_resolver_override=FakeRegionResolver(),
    )
    decision = engine.route(RouteRequest(input_text="近7天链路时延分布"))
    payload = decision.to_dict()
    assert payload["type"] == "route_nl2sql"


def test_seed_scope_guard_enabled_blocks_out_of_seed_scope(tmp_path):
    cfg_dir = _build_temp_config(tmp_path, enable_guard=True, min_score=0.9)
    engine = build_engine(
        config_dir=str(cfg_dir),
        retriever_override=_SeedScopeRetriever(seed_score=0.2),
        device_resolver_override=FakeDeviceResolver(),
        region_resolver_override=FakeRegionResolver(),
    )
    decision = engine.route(RouteRequest(input_text="近7天链路时延分布"))
    payload = decision.to_dict()
    assert payload["type"] == "refuse"
    assert payload["out_of_scope_reason"] == "out_of_seed_scope"
