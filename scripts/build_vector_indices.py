from __future__ import annotations

import argparse
from typing import Any

from chat_pre_check.infrastructure.config.loader import load_app_config
from chat_pre_check.infrastructure.embedding.e5_embedder import E5Embedder
from chat_pre_check.infrastructure.resolvers.search_client_factory import (
    build_search_client,
)


def build_scene_docs(scenes: list[dict[str, Any]], embedder: E5Embedder) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    texts: list[str] = []
    ids: list[str] = []
    metas: list[dict[str, Any]] = []
    for scene in scenes:
        scene_id = scene["scene_id"]
        lines = [scene.get("description", "")] + scene.get("examples", [])
        for idx, text in enumerate(lines):
            doc_id = f"{scene_id}_{idx}"
            ids.append(doc_id)
            texts.append(text)
            metas.append({"scene_id": scene_id})
    vectors = embedder.encode_passages(texts)
    for doc_id, text, vector, meta in zip(ids, texts, vectors, metas):
        docs.append(
            {
                "id": doc_id,
                "scene_id": meta["scene_id"],
                "text": text,
                "metadata": {"scene_id": meta["scene_id"]},
                "vector": vector.tolist(),
            }
        )
    return docs


def build_template_docs(
    templates: list[dict[str, Any]], embedder: E5Embedder
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    texts: list[str] = []
    ids: list[str] = []
    metas: list[dict[str, Any]] = []
    for template in templates:
        template_id = template["template_id"]
        scene_id = template["scene_id"]
        lines = template.get("examples", []) + template.get("keywords", [])
        for idx, text in enumerate(lines):
            doc_id = f"{template_id}_{idx}"
            ids.append(doc_id)
            texts.append(text)
            metas.append({"scene_id": scene_id, "template_id": template_id})
    vectors = embedder.encode_passages(texts)
    for doc_id, text, vector, meta in zip(ids, texts, vectors, metas):
        docs.append(
            {
                "id": doc_id,
                "scene_id": meta["scene_id"],
                "template_id": meta["template_id"],
                "text": text,
                "metadata": meta,
                "vector": vector.tolist(),
            }
        )
    return docs


def build_seed_case_docs(seed_cases: list[dict[str, Any]], embedder: E5Embedder) -> list[dict[str, Any]]:
    if not seed_cases:
        return []
    texts = [case["text"] for case in seed_cases]
    vectors = embedder.encode_passages(texts)
    docs: list[dict[str, Any]] = []
    for case, vector in zip(seed_cases, vectors):
        metadata = {
            "case_id": case["case_id"],
            "scene_id": case.get("scene_id"),
            "label": case.get("label", case["text"]),
            "route_type": case.get("route_type", "route_nl2sql"),
            "tags": case.get("tags", []),
            "priority": case.get("priority", 100),
            "owner": case.get("owner", ""),
            "risk_level": case.get("risk_level", "medium"),
        }
        if case.get("template_id"):
            metadata["template_id"] = case.get("template_id")
        docs.append(
            {
                "id": case["case_id"],
                "scene_id": case.get("scene_id"),
                "text": case["text"],
                "metadata": metadata,
                "vector": vector.tolist(),
            }
        )
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build vector indices for OpenSearch or Elasticsearch"
    )
    parser.add_argument(
        "--search-url",
        "--os",
        dest="os_url",
        required=True,
        help="Search backend base URL",
    )
    parser.add_argument(
        "--search-backend",
        choices=["opensearch", "elasticsearch", "es"],
        default=None,
        help="Search backend type. Default reads CHAT_PRE_CHECK_SEARCH_BACKEND or vector.search_backend.",
    )
    parser.add_argument("--config-dir", default="configs")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    config = load_app_config(args.config_dir)
    vector_cfg = config.vector
    embedder = E5Embedder(
        model_name=vector_cfg["model_name"],
        device=vector_cfg.get("device", "cpu"),
    )
    backend, client = build_search_client(
        vector_cfg=vector_cfg,
        base_url=args.os_url,
        backend_override=args.search_backend,
        username=args.username,
        password=args.password,
    )

    scene_docs = build_scene_docs(config.scenes, embedder)
    template_docs = build_template_docs(config.templates, embedder)
    seed_docs = build_seed_case_docs(config.seed_cases, embedder)

    client.ensure_vector_index(vector_cfg["scene_index"], dimension=768)
    client.ensure_vector_index(vector_cfg["template_index"], dimension=768)
    client.ensure_vector_index(vector_cfg["seed_case_index"], dimension=768)
    client.bulk_index(vector_cfg["scene_index"], scene_docs)
    client.bulk_index(vector_cfg["template_index"], template_docs)
    if seed_docs:
        client.bulk_index(vector_cfg["seed_case_index"], seed_docs)
    print(
        f"indexed scene_docs={len(scene_docs)} template_docs={len(template_docs)} "
        f"seed_docs={len(seed_docs)} into "
        f"{vector_cfg['scene_index']}/{vector_cfg['template_index']}/{vector_cfg['seed_case_index']} "
        f"(backend={backend})"
    )


if __name__ == "__main__":
    main()
