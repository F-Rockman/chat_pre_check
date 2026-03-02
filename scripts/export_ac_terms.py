from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any, Iterable

from chat_pre_check.infrastructure.config.loader import load_app_config
from chat_pre_check.infrastructure.resolvers.search_client_factory import build_search_client


def _to_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_aliases(*values: Any) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        for item in _to_list(value):
            text = _clean_text(item)
            if not text:
                continue
            key = text.lower()
            if key not in seen:
                seen[key] = text
    return list(seen.values())


def _is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except Exception:
        return False


def _choose(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _term_key(term: dict[str, Any]) -> str:
    return (
        f"{_clean_text(term.get('slot')).lower()}|"
        f"{_clean_text(term.get('value')).lower()}|"
        f"{_clean_text(term.get('entity_id')).lower()}|"
        f"{_clean_text(term.get('term')).lower()}"
    )


def _merge_terms(
    terms: Iterable[dict[str, Any]],
    *,
    min_term_length: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in terms:
        term_text = _clean_text(raw.get("term"))
        if len(term_text) < min_term_length:
            continue
        slot = _clean_text(raw.get("slot"))
        if not slot:
            continue
        cleaned = {
            "term": term_text,
            "slot": slot,
            "value": raw.get("value"),
            "entity_id": _clean_text(raw.get("entity_id")) or None,
            "entity_name": _clean_text(raw.get("entity_name")) or None,
            "aliases": _clean_aliases(raw.get("aliases", [])),
            "score": _normalize_score(raw.get("score", 0.99)),
            "word_boundary": raw.get("word_boundary"),
            "metadata": _to_dict(raw.get("metadata", {})),
        }
        key = _term_key(cleaned)
        prev = merged.get(key)
        if prev is None:
            merged[key] = cleaned
            continue
        prev["aliases"] = _clean_aliases(prev.get("aliases", []), cleaned.get("aliases", []))
        prev["score"] = max(float(prev.get("score", 0.0)), float(cleaned.get("score", 0.0)))
        if len(_to_dict(cleaned.get("metadata", {}))) > len(_to_dict(prev.get("metadata", {}))):
            prev["metadata"] = cleaned["metadata"]
        if prev.get("word_boundary") is None:
            prev["word_boundary"] = cleaned.get("word_boundary")

    items = list(merged.values())
    for item in items:
        aliases = [alias for alias in _clean_aliases(item.get("aliases", [])) if alias != item["term"]]
        item["aliases"] = aliases
    items.sort(key=lambda item: (item["slot"], item["term"]))
    return items


def _normalize_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.99
    return max(0.0, min(1.0, score))


def _scan_index_docs(
    *,
    raw_client: Any,
    index_name: str,
    batch_size: int,
    max_docs: int,
) -> list[dict[str, Any]]:
    if not index_name:
        return []

    docs: list[dict[str, Any]] = []
    scroll_id: str | None = None
    try:
        response = raw_client.search(
            index=index_name,
            body={"query": {"match_all": {}}, "sort": ["_doc"]},
            scroll="2m",
            size=batch_size,
        )
        scroll_id = response.get("_scroll_id")
        while True:
            hits = _to_dict(response).get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                docs.append(_to_dict(hit).get("_source", {}))
                if max_docs > 0 and len(docs) >= max_docs:
                    return docs
            if not scroll_id:
                break
            response = raw_client.scroll(scroll_id=scroll_id, scroll="2m")
    except Exception:
        docs = _scan_index_docs_fallback(
            raw_client=raw_client,
            index_name=index_name,
            batch_size=batch_size,
            max_docs=max_docs,
        )
    finally:
        if scroll_id:
            try:
                raw_client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass
    return docs


def _scan_index_docs_fallback(
    *,
    raw_client: Any,
    index_name: str,
    batch_size: int,
    max_docs: int,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    offset = 0
    while True:
        if max_docs > 0 and len(docs) >= max_docs:
            return docs
        size = batch_size
        if max_docs > 0:
            size = min(size, max_docs - len(docs))
        response = raw_client.search(
            index=index_name,
            body={
                "from": offset,
                "size": size,
                "query": {"match_all": {}},
                "sort": ["_doc"],
            },
        )
        hits = _to_dict(response).get("hits", {}).get("hits", [])
        if not hits:
            break
        for hit in hits:
            docs.append(_to_dict(hit).get("_source", {}))
        offset += size
    return docs


def _device_terms(docs: list[dict[str, Any]], *, include_ip: bool) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    for source in docs:
        metadata = _to_dict(source.get("metadata", {}))
        entity_id = _choose(
            source.get("id"),
            source.get("device_id"),
            metadata.get("id"),
            metadata.get("device_id"),
        )
        entity_name = _choose(
            source.get("name"),
            source.get("hostname"),
            metadata.get("name"),
            metadata.get("hostname"),
            source.get("ip"),
            metadata.get("ip"),
        )
        if not entity_id or not entity_name:
            continue
        aliases = _clean_aliases(
            source.get("aliases"),
            source.get("alias"),
            source.get("hostname"),
            metadata.get("aliases"),
            metadata.get("alias"),
        )
        terms.append(
            {
                "term": entity_name,
                "slot": "device_id",
                "value": entity_id,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "aliases": aliases,
                "score": 0.99,
                "metadata": {"domain": "device"},
            }
        )
        if include_ip:
            ip = _choose(source.get("ip"), source.get("ipv4"), metadata.get("ip"))
            if ip and _is_valid_ipv4(ip):
                terms.append(
                    {
                        "term": ip,
                        "slot": "device_id",
                        "value": entity_id,
                        "entity_id": entity_id,
                        "entity_name": entity_name,
                        "aliases": [],
                        "score": 0.995,
                        "metadata": {"domain": "device", "from": "ip"},
                        "word_boundary": True,
                    }
                )
    return terms


def _region_terms(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    for source in docs:
        metadata = _to_dict(source.get("metadata", {}))
        entity_id = _choose(
            source.get("id"),
            source.get("region_id"),
            source.get("code"),
            metadata.get("id"),
            metadata.get("region_id"),
            metadata.get("code"),
        )
        entity_name = _choose(
            source.get("name"),
            source.get("region_name"),
            metadata.get("name"),
            metadata.get("region_name"),
        )
        if not entity_id or not entity_name:
            continue
        aliases = _clean_aliases(
            source.get("aliases"),
            source.get("alias"),
            metadata.get("aliases"),
            metadata.get("alias"),
            metadata.get("abbr"),
        )
        terms.append(
            {
                "term": entity_name,
                "slot": "region_id",
                "value": entity_id,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "aliases": aliases,
                "score": 0.99,
                "metadata": {"domain": "region"},
            }
        )
    return terms


def _load_existing_terms(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        terms = payload.get("terms", [])
        if isinstance(terms, list):
            return [item for item in terms if isinstance(item, dict)]
    return []


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export device/region terms from search DB and generate ac_terms.json"
    )
    parser.add_argument(
        "--search-url",
        "--os",
        dest="search_url",
        required=True,
        help="Search backend base URL, e.g. http://localhost:9200",
    )
    parser.add_argument(
        "--search-backend",
        choices=["opensearch", "elasticsearch", "es"],
        default=None,
        help="Search backend type. Default reads CHAT_PRE_CHECK_SEARCH_BACKEND or vector.search_backend.",
    )
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--output", default="configs/ac_terms.json")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--bearer-token", default=None)
    parser.add_argument("--device-index", default=None)
    parser.add_argument("--region-index", default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-docs", type=int, default=0, help="0 means no limit")
    parser.add_argument("--min-term-length", type=int, default=2)
    parser.add_argument("--no-device-ip", action="store_true", help="Disable exporting IP terms")
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge with existing output file terms instead of overwrite from scratch.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = load_app_config(args.config_dir)
    vector_cfg = config.vector
    backend, client = build_search_client(
        vector_cfg=vector_cfg,
        base_url=args.search_url,
        backend_override=args.search_backend,
        username=args.username,
        password=args.password,
        bearer_token=args.bearer_token,
    )
    raw_client = getattr(client, "client", None)
    if raw_client is None:
        raise RuntimeError("search client does not expose raw client for scan export")

    device_index = args.device_index or vector_cfg.get("device_index", "assets_device_v1")
    region_index = args.region_index or vector_cfg.get("region_index", "assets_region_v1")
    batch_size = max(1, int(args.batch_size))
    max_docs = max(0, int(args.max_docs))
    min_term_length = max(1, int(args.min_term_length))

    device_docs: list[dict[str, Any]] = []
    region_docs: list[dict[str, Any]] = []
    if client.index_exists(device_index):
        device_docs = _scan_index_docs(
            raw_client=raw_client,
            index_name=device_index,
            batch_size=batch_size,
            max_docs=max_docs,
        )
    else:
        print(f"skip missing index: {device_index}")
    if client.index_exists(region_index):
        region_docs = _scan_index_docs(
            raw_client=raw_client,
            index_name=region_index,
            batch_size=batch_size,
            max_docs=max_docs,
        )
    else:
        print(f"skip missing index: {region_index}")

    generated = _device_terms(device_docs, include_ip=not args.no_device_ip)
    generated.extend(_region_terms(region_docs))

    output_path = Path(args.output)
    merged_input = list(generated)
    if args.merge_existing:
        merged_input.extend(_load_existing_terms(output_path))

    terms = _merge_terms(merged_input, min_term_length=min_term_length)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(terms, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "exported "
        f"device_docs={len(device_docs)} region_docs={len(region_docs)} "
        f"terms={len(terms)} output={output_path} backend={backend}"
    )


if __name__ == "__main__":
    main()
