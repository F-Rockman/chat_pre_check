from __future__ import annotations

from scripts.export_ac_terms import _device_terms, _merge_terms, _region_terms


def test_device_terms_include_ip_mapping() -> None:
    docs = [
        {
            "id": "dev_1",
            "name": "核心路由器R1",
            "ip": "10.2.3.4",
            "aliases": ["R1", "Core-R1"],
        }
    ]
    terms = _device_terms(docs, include_ip=True)
    merged = _merge_terms(terms, min_term_length=2)
    keys = {(item["slot"], item["term"]) for item in merged}
    assert ("device_id", "核心路由器R1") in keys
    assert ("device_id", "10.2.3.4") in keys


def test_region_terms_and_merge_dedup() -> None:
    docs = [
        {"id": "east_cn", "name": "华东", "aliases": ["华东区"]},
        {"id": "east_cn", "name": "华东", "aliases": ["华东大区"]},
    ]
    terms = _region_terms(docs)
    merged = _merge_terms(terms, min_term_length=2)
    assert len(merged) == 1
    assert merged[0]["slot"] == "region_id"
    assert merged[0]["term"] == "华东"
    assert "华东区" in merged[0]["aliases"]
    assert "华东大区" in merged[0]["aliases"]
