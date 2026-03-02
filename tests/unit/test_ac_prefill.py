from __future__ import annotations

from chat_pre_check.infrastructure.extractors.ac_prefill import ACSlotPrefiller, PrefillTerm


def test_ascii_boundary_blocks_substring_false_positive() -> None:
    prefiller = ACSlotPrefiller(
        [PrefillTerm(term="bgp", slot="protocol", value="bgp", score=0.9)],
        default_word_boundary=True,
    )
    bad = prefiller.match("dbgp flap 告警")
    ok = prefiller.match("bgp flap 告警")
    assert "protocol" not in bad.slot_matches
    assert ok.slot_matches["protocol"][0].resolved_slot_value() == "bgp"


def test_max_matches_protects_memory_growth() -> None:
    prefiller = ACSlotPrefiller(
        [PrefillTerm(term="a", slot="tag", value="x", score=0.6)],
        min_term_length=1,
        default_word_boundary=False,
        max_matches=3,
    )
    result = prefiller.match("aaaaaa")
    assert len(result.matches) == 3


def test_duplicate_terms_keep_higher_score() -> None:
    prefiller = ACSlotPrefiller(
        [
            PrefillTerm(term="华东", slot="region_id", value="east_cn", score=0.6),
            PrefillTerm(term="华东", slot="region_id", value="east_cn", score=0.95),
        ]
    )
    result = prefiller.match("查询华东离线设备")
    assert result.slot_candidates["region_id"][0].score == 0.95
