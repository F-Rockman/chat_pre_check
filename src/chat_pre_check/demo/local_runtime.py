from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from chat_pre_check.application.services.scoring import (
    example_similarity_score,
    keyword_overlap_score,
)
from chat_pre_check.bootstrap import build_engine
from chat_pre_check.domain.models import Candidate, SearchHit
from chat_pre_check.infrastructure.config.loader import load_app_config


IP_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")


class LocalHeuristicRetriever:
    """OpenSearch-free retriever for local/low-dependency runtime."""

    SCENE_ALARM_QUERY = "alarm.query"
    SCENE_ALARM_ANALYSIS = "alarm.analysis"
    SCENE_DEVICE_QUERY = "device.query"
    SCENE_TICKET_ANALYSIS = "ticket.analysis"

    def __init__(
        self,
        scenes: list[dict[str, Any]],
        templates: list[dict[str, Any]],
        seed_cases: list[dict[str, Any]] | None = None,
    ) -> None:
        self.scenes = scenes
        self.templates = templates
        self.seed_cases = seed_cases or []
        self.scene_ids = {scene.get("scene_id") for scene in scenes}

    def search_scene(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        hinted = self._pattern_scene_hits(query_text, topk=topk)
        if hinted:
            return hinted

        scored: list[SearchHit] = []
        for scene in self.scenes:
            scene_id = scene["scene_id"]
            score = self._score_text(
                query_text=query_text,
                keywords=scene.get("keywords", []),
                examples=scene.get("examples", []),
            )
            scored.append(
                SearchHit(
                    doc_id=f"scene::{scene_id}",
                    score=score,
                    metadata={"scene_id": scene_id},
                )
            )
        return self._topk(scored, topk)

    def _pattern_scene_hits(self, query_text: str, topk: int) -> list[SearchHit]:
        text = query_text.lower()
        candidates: list[tuple[str, float]] = []

        if "近24小时告警" in text and "top" not in text:
            candidates = [
                (self.SCENE_ALARM_QUERY, 0.93),
                (self.SCENE_ALARM_ANALYSIS, 0.88),
            ]
        elif any(token in text for token in ("接口", "bgp", "ospf", "isis", "flap", "错误包")):
            candidates = [
                (self.SCENE_ALARM_QUERY, 0.95),
                (self.SCENE_ALARM_ANALYSIS, 0.68),
            ]
        elif "健康分" in text:
            candidates = [
                (self.SCENE_DEVICE_QUERY, 0.95),
                (self.SCENE_ALARM_ANALYSIS, 0.75),
            ]
        elif any(
            token in text
            for token in ("丢包", "时延", "延迟", "抖动", "带宽", "吞吐", "p95", "相关性", "占比", "环比", "同比", "热力")
        ):
            candidates = [
                (self.SCENE_ALARM_ANALYSIS, 0.95),
                (self.SCENE_TICKET_ANALYSIS, 0.60),
            ]
        elif any(token in text for token in ("cpu", "内存", "离线", "设备", "利用率", "分位数")):
            candidates = [
                (self.SCENE_DEVICE_QUERY, 0.95),
                (self.SCENE_ALARM_QUERY, 0.70),
            ]
        elif "工单" in text:
            candidates = [
                (self.SCENE_TICKET_ANALYSIS, 0.94),
                (self.SCENE_ALARM_ANALYSIS, 0.90),
            ]
        elif "告警" in text:
            candidates = [
                (self.SCENE_ALARM_QUERY, 0.96),
                (self.SCENE_ALARM_ANALYSIS, 0.70),
            ]

        if not candidates:
            return []

        hits: list[SearchHit] = []
        for idx, (scene_id, score) in enumerate(candidates, start=1):
            if scene_id not in self.scene_ids:
                continue
            hits.append(
                SearchHit(
                    doc_id=f"scene_hint::{idx}",
                    score=score,
                    metadata={"scene_id": scene_id},
                )
            )
        return self._topk(hits, topk)

    def search_template(
        self, scene_id: str, query_text: str, topk: int = 5
    ) -> list[SearchHit]:
        scored: list[SearchHit] = []
        for template in self.templates:
            if template.get("scene_id") != scene_id:
                continue
            template_id = template["template_id"]
            score = self._score_text(
                query_text=query_text,
                keywords=template.get("keywords", []),
                examples=template.get("examples", []),
            )
            scored.append(
                SearchHit(
                    doc_id=f"template::{template_id}",
                    score=score,
                    metadata={"template_id": template_id, "scene_id": scene_id},
                )
            )
        return self._topk(scored, topk)

    def search_seed_cases(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        scored: list[SearchHit] = []
        for case in self.seed_cases:
            case_id = case["case_id"]
            text = case.get("text", "")
            label = case.get("label", text)
            score = max(
                example_similarity_score(query_text, [text, label]),
                keyword_overlap_score(query_text, case.get("tags", [])),
            )
            scored.append(
                SearchHit(
                    doc_id=f"seed::{case_id}",
                    score=score,
                    metadata={
                        "case_id": case_id,
                        "scene_id": case.get("scene_id"),
                        "label": label,
                    },
                )
            )
        return self._topk(scored, topk)

    @staticmethod
    def _score_text(query_text: str, keywords: list[str], examples: list[str]) -> float:
        return max(
            keyword_overlap_score(query_text, keywords),
            example_similarity_score(query_text, examples),
        )

    @staticmethod
    def _topk(items: list[SearchHit], k: int) -> list[SearchHit]:
        items.sort(key=lambda x: x.score, reverse=True)
        return items[:k]


class LocalDeviceResolver:
    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        candidates: list[Candidate] = []
        match = IP_RE.search(text)
        if match:
            ip = match.group(0)
            candidates.append(Candidate(f"dev_{ip.replace('.', '_')}", f"设备{ip}", 0.9))
        lowered = text.lower()
        if "核心路由器r1" in lowered or " r1 " in f" {lowered} ":
            candidates.append(Candidate("dev_r1", "核心路由器R1", 0.85))
        if "olt-01" in lowered:
            candidates.append(Candidate("dev_olt_01", "OLT-01", 0.84))
        return candidates[:topk]


class LocalRegionResolver:
    REGION_MAP = {
        "北京": ("region_bj", "北京"),
        "上海": ("region_sh", "上海"),
        "广州": ("region_gz", "广州"),
        "深圳": ("region_sz", "深圳"),
        "华东": ("east_cn", "华东"),
        "华南": ("south_cn", "华南"),
        "华北": ("north_cn", "华北"),
        "华中": ("central_cn", "华中"),
        "西北": ("northwest_cn", "西北"),
        "西南": ("southwest_cn", "西南"),
    }

    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        results: list[Candidate] = []
        for token, (region_id, name) in self.REGION_MAP.items():
            if token in text:
                results.append(Candidate(region_id, name, 0.88))
        return results[:topk]


def build_local_fallback_engine(config_dir: str = "configs"):
    config = load_app_config(config_dir)
    seed_cases = _load_seed_cases(Path(config_dir) / "seed_cases.json")
    retriever = LocalHeuristicRetriever(
        scenes=config.scenes,
        templates=config.templates,
        seed_cases=seed_cases,
    )
    return build_engine(
        config_dir=config_dir,
        retriever_override=retriever,
        device_resolver_override=LocalDeviceResolver(),
        region_resolver_override=LocalRegionResolver(),
    )


def _load_seed_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
