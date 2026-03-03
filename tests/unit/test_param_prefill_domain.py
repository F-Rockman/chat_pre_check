from __future__ import annotations

from chat_pre_check.application.middlewares.param_prefill import (
    PrefillArbiter,
    PrefillDomainRouter,
)
from chat_pre_check.domain.models import RequestContext
from chat_pre_check.infrastructure.extractors.ac_prefill import (
    ACPrefillResult,
    ACMatch,
    ACDomainPrefillManager,
    PrefillTerm,
)


def test_domain_manager_respects_selected_domains() -> None:
    manager = ACDomainPrefillManager.from_terms(
        terms=[
            PrefillTerm(
                term="华东",
                domain="region",
                slot="region_id",
                value="east_cn",
                entity_id="east_cn",
                entity_name="华东",
                score=0.95,
            ),
            PrefillTerm(
                term="10.2.3.4",
                domain="device",
                slot="device_id",
                value="dev_10_2_3_4",
                entity_id="dev_10_2_3_4",
                entity_name="设备10.2.3.4",
                score=0.95,
            ),
        ],
        ignore_case=True,
        min_term_length=2,
        default_word_boundary=True,
        max_matches=50,
        domain_priority={"region": 1.0, "device": 0.9},
    )
    results = manager.match_by_domain("查询华东离线设备", domains=["region"])
    assert "region" in results
    assert "device" not in results
    assert results["region"].slot_matches["region_id"][0].resolved_slot_value() == "east_cn"


def test_domain_router_uses_scene_and_keyword_constraints() -> None:
    router = PrefillDomainRouter(
        {
            "enabled": True,
            "max_domains": 2,
            "scene_domains": {"device.query": ["device", "region"]},
            "keyword_domains": {"kpi": ["cpu", "内存"]},
            "default_domains": ["alarm"],
        }
    )
    ctx = RequestContext(
        input_text="查cpu",
        norm_text="查cpu",
        context_scene="device.query",
    )
    selected = router.select_domains(
        ctx=ctx,
        text=ctx.norm_text,
        available_domains=["device", "region", "kpi", "alarm"],
    )
    assert selected == ["device", "region"]


def test_prefill_arbiter_applies_slot_domain_priority() -> None:
    arbiter = PrefillArbiter(
        {
            "domain_priority": {"alarm": 1.0, "kpi": 0.8},
            "slot_domain_priority": {"metric": ["kpi"]},
            "domain_penalty": 0.2,
        }
    )
    by_domain = {
        "alarm": ACPrefillResult(
            matches=[],
            slot_matches={
                "metric": [
                    ACMatch(
                        keyword="时延",
                        matched_text="时延",
                        start=0,
                        end=1,
                        slot="metric",
                        slot_value="latency_alarm",
                        entity_id=None,
                        entity_name=None,
                        score=0.95,
                        metadata={"prefill_domain": "alarm"},
                    )
                ]
            },
            slot_candidates={},
        ),
        "kpi": ACPrefillResult(
            matches=[],
            slot_matches={
                "metric": [
                    ACMatch(
                        keyword="时延",
                        matched_text="时延",
                        start=0,
                        end=1,
                        slot="metric",
                        slot_value="latency_kpi",
                        entity_id=None,
                        entity_name=None,
                        score=0.90,
                        metadata={"prefill_domain": "kpi"},
                    )
                ]
            },
            slot_candidates={},
        ),
    }
    merged = arbiter.merge(by_domain=by_domain, max_candidates_per_slot=3)
    top = merged.slot_matches["metric"][0]
    assert top.resolved_slot_value() == "latency_kpi"
    assert top.metadata.get("prefill_domain") == "kpi"


def test_domain_manager_prefers_high_priority_when_scores_equal() -> None:
    manager = ACDomainPrefillManager.from_terms(
        terms=[
            PrefillTerm(
                term="cpu",
                domain="alarm",
                slot="metric",
                value="cpu_alarm",
                score=0.9,
                word_boundary=True,
            ),
            PrefillTerm(
                term="cpu",
                domain="kpi",
                slot="metric",
                value="cpu_kpi",
                score=0.9,
                word_boundary=True,
            ),
        ],
        ignore_case=True,
        min_term_length=2,
        default_word_boundary=True,
        max_matches=20,
        domain_priority={"alarm": 1.0, "kpi": 0.5},
    )
    merged = manager.match("查询cpu趋势", domains=["kpi", "alarm"], max_candidates_per_slot=3)
    top = merged.slot_matches["metric"][0]
    assert top.resolved_slot_value() == "cpu_alarm"
    assert top.metadata.get("prefill_domain") == "alarm"
