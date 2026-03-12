from __future__ import annotations

import time
from typing import Any

from chat_pre_check.domain.models import Candidate, RequestContext, RouteDecision, TraceStep
from chat_pre_check.infrastructure.extractors.ac_prefill import (
    ACPrefillResult,
    ACMatch,
    ACDomainPrefillManager,
    ACSlotPrefiller,
)


class PrefillDomainRouter:
    """预提参域路由器：根据场景/关键词/槽位选择本轮参与匹配的业务域。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.max_domains = max(1, int(cfg.get("max_domains", 2)))
        self.default_domains = self._normalize_text_list(cfg.get("default_domains", []))
        self.keyword_domains = self._normalize_mapping(cfg.get("keyword_domains", {}))
        self.scene_domains = self._normalize_mapping(cfg.get("scene_domains", {}))
        self.slot_domains = self._normalize_mapping(cfg.get("slot_domains", {}))

    def select_domains(
        self,
        *,
        ctx: RequestContext,
        text: str,
        available_domains: list[str],
    ) -> list[str]:
        if not available_domains:
            return []
        if not self.enabled:
            return available_domains[: self.max_domains]

        available_set = set(available_domains)
        selected: list[str] = []
        seen: set[str] = set()

        # 选择顺序按“上下文场景 -> 当前场景 -> 已有槽位 -> 关键词”收敛，尽量少扫无关域。
        for domain in self._domains_for_scene(ctx.context_scene):
            self._append(domain, selected, seen, available_set)
        for domain in self._domains_for_scene(ctx.scene):
            self._append(domain, selected, seen, available_set)

        for slot_name in list(ctx.slots.keys()):
            for domain in self.slot_domains.get(slot_name, []):
                self._append(domain, selected, seen, available_set)

        lowered = text.lower()
        for domain, keywords in self.keyword_domains.items():
            if any(keyword in lowered for keyword in keywords):
                self._append(domain, selected, seen, available_set)

        if not selected:
            for domain in self.default_domains:
                self._append(domain, selected, seen, available_set)
        if not selected:
            selected = list(available_domains)
        return selected[: self.max_domains]

    def _domains_for_scene(self, scene: str | None) -> list[str]:
        if not scene:
            return []
        return self.scene_domains.get(scene, [])

    @staticmethod
    def _append(
        domain: str,
        selected: list[str],
        seen: set[str],
        available: set[str],
    ) -> None:
        if not domain or domain in seen or domain not in available:
            return
        seen.add(domain)
        selected.append(domain)

    @staticmethod
    def _normalize_text_list(items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @classmethod
    def _normalize_mapping(cls, value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        mapping: dict[str, list[str]] = {}
        for key, raw in value.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            mapping[normalized_key] = cls._normalize_text_list(raw)
        return mapping


class PrefillArbiter:
    """跨域仲裁器：合并多域命中并处理同槽位冲突。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.domain_priority = self._to_float_mapping(cfg.get("domain_priority", {}))
        self.slot_domain_priority = self._normalize_slot_domain_priority(
            cfg.get("slot_domain_priority", {})
        )
        self.domain_penalty = max(0.0, float(cfg.get("domain_penalty", 0.2)))

    def merge(
        self,
        *,
        by_domain: dict[str, ACPrefillResult],
        max_candidates_per_slot: int,
    ) -> ACPrefillResult:
        all_matches: list[ACMatch] = []
        slot_bucket: dict[str, dict[str, ACMatch]] = {}
        for domain, result in by_domain.items():
            all_matches.extend(result.matches)
            for slot_name, hits in result.slot_matches.items():
                bucket = slot_bucket.setdefault(slot_name, {})
                for hit in hits:
                    # 同槽位命中相同规范化值时，仅保留排序更优的一条，避免跨域重复候选污染。
                    key = f"{slot_name}:{hit.resolved_slot_value()}"
                    prev = bucket.get(key)
                    if prev is None or self._rank_key(slot_name, hit) < self._rank_key(
                        slot_name, prev
                    ):
                        bucket[key] = hit

        slot_matches: dict[str, list[ACMatch]] = {}
        slot_candidates: dict[str, list[Candidate]] = {}
        for slot_name, deduped in slot_bucket.items():
            ranked = sorted(deduped.values(), key=lambda item: self._rank_key(slot_name, item))
            if not ranked:
                continue
            slot_matches[slot_name] = ranked
            slot_candidates[slot_name] = [
                self._to_candidate(slot_name, item)
                for item in ranked[: max(1, int(max_candidates_per_slot))]
            ]

        return ACPrefillResult(
            matches=all_matches,
            slot_matches=slot_matches,
            slot_candidates=slot_candidates,
        )

    def _rank_key(self, slot_name: str, item: ACMatch) -> tuple[float, float, int, int]:
        # 排序优先级：有效分(含惩罚) > 域优先级 > 词长 > 位置。
        domain = str(item.metadata.get("prefill_domain", ""))
        score = float(item.score) - self._penalty(slot_name, domain)
        priority = float(self.domain_priority.get(domain, 0.0))
        length = item.end - item.start + 1
        return (-score, -priority, -length, item.start)

    def _penalty(self, slot_name: str, domain: str) -> float:
        allowed = self.slot_domain_priority.get(slot_name, [])
        if not allowed:
            return 0.0
        if domain in allowed:
            return 0.0
        return self.domain_penalty

    @staticmethod
    def _to_candidate(slot_name: str, item: ACMatch) -> Candidate:
        entity_id = str(item.entity_id) if item.entity_id is not None else str(item.resolved_slot_value())
        return Candidate(
            entity_id=entity_id,
            name=item.entity_name or item.matched_text,
            score=max(0.0, min(1.0, float(item.score))),
            meta={
                "source": "ac_prefill",
                "keyword": item.keyword,
                "slot": slot_name,
                "prefill_domain": str(item.metadata.get("prefill_domain", "")),
            },
        )

    @staticmethod
    def _to_float_mapping(value: Any) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, float] = {}
        for key, raw in value.items():
            name = str(key).strip()
            if not name:
                continue
            try:
                result[name] = float(raw)
            except (TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _normalize_slot_domain_priority(value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        mapping: dict[str, list[str]] = {}
        for slot_name, raw in value.items():
            if not isinstance(raw, list):
                continue
            values: list[str] = []
            seen: set[str] = set()
            for item in raw:
                domain = str(item).strip()
                if not domain or domain in seen:
                    continue
                seen.add(domain)
                values.append(domain)
            mapping[str(slot_name)] = values
        return mapping


class ParamPrefillMiddleware:
    """参数预填中间件：AC 命中后产出候选，并可按阈值自动回填槽位。"""

    name = "param_prefill"

    def __init__(
        self,
        *,
        prefiller: ACSlotPrefiller | ACDomainPrefillManager | None,
        enabled: bool = False,
        auto_commit: bool = True,
        commit_score: float = 0.95,
        min_gap: float = 0.05,
        max_candidates_per_slot: int = 3,
        max_trace_matches: int = 10,
        router_config: dict[str, Any] | None = None,
        arbiter_config: dict[str, Any] | None = None,
    ) -> None:
        self.prefiller = prefiller
        self.enabled = bool(enabled and prefiller is not None)
        self.auto_commit = bool(auto_commit)
        self.commit_score = float(commit_score)
        self.min_gap = float(min_gap)
        self.max_candidates_per_slot = max(1, int(max_candidates_per_slot))
        self.max_trace_matches = max(1, int(max_trace_matches))
        self.domain_router = PrefillDomainRouter(router_config)
        self.arbiter = PrefillArbiter(arbiter_config)

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if not self.enabled:
            return self._trace_continue(ctx, started, reason="prefill_disabled")

        text = ctx.norm_text or ctx.input_text
        domain_results, selected_domains = self._match_by_domain(ctx=ctx, text=text)
        result = self.arbiter.merge(
            by_domain=domain_results,
            max_candidates_per_slot=self.max_candidates_per_slot,
        )
        if not result.matches:
            return self._trace_continue(ctx, started, reason="prefill_no_match")

        committed_slots: dict[str, Any] = {}
        if self.auto_commit:
            # 仅提交高置信且有明显领先优势的候选，降低误填风险。
            for slot_name, ranked in result.slot_matches.items():
                if not ranked:
                    continue
                if ctx.slots.get(slot_name) not in (None, ""):
                    continue
                top1 = ranked[0]
                top2 = ranked[1] if len(ranked) > 1 else None
                gap = float(top1.score) - float(top2.score) if top2 else float(top1.score)
                if float(top1.score) >= self.commit_score and gap >= self.min_gap:
                    committed_slots[slot_name] = top1.resolved_slot_value()
                    ctx.slots[slot_name] = top1.resolved_slot_value()

        merged_candidates = 0
        for slot_name, candidates in result.slot_candidates.items():
            key = self._candidate_key(slot_name)
            if not key:
                continue
            # 与现有候选融合去重，保留更高分结果。
            existing = self._normalize_candidates(ctx.entities.get(key, []))
            merged = self._merge_candidates(existing, candidates)
            ctx.entities[key] = merged
            merged_candidates += len(merged)

        ctx.entities["ac_prefill_matches"] = [
            match.to_trace() for match in result.matches[: self.max_trace_matches]
        ]
        ctx.entities["ac_prefill_slots"] = sorted(result.slot_matches.keys())
        ctx.entities["ac_prefill_domains"] = selected_domains
        ctx.entities["ac_prefill_domain_match_counts"] = {
            domain: len(payload.matches) for domain, payload in domain_results.items()
        }
        if committed_slots:
            ctx.entities["ac_prefill_committed"] = committed_slots

        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.summary["prefill_committed_slots"] = sorted(committed_slots.keys())
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="prefill_applied",
                latency_ms=elapsed,
                extra={
                    "match_count": len(result.matches),
                    "slot_count": len(result.slot_matches),
                    "committed_slots": committed_slots,
                    "merged_candidates": merged_candidates,
                    "domains": selected_domains,
                },
            )
        )
        return None

    def _match_by_domain(
        self,
        *,
        ctx: RequestContext,
        text: str,
    ) -> tuple[dict[str, ACPrefillResult], list[str]]:
        if isinstance(self.prefiller, ACDomainPrefillManager):
            # 多域模式：先选域，再按域匹配，最终交由仲裁器统一合并。
            available_domains = self.prefiller.available_domains()
            selected = self.domain_router.select_domains(
                ctx=ctx,
                text=text,
                available_domains=available_domains,
            )
            return (
                self.prefiller.match_by_domain(
                    text,
                    domains=selected,
                    max_candidates_per_slot=self.max_candidates_per_slot,
                ),
                selected,
            )

        if isinstance(self.prefiller, ACSlotPrefiller):
            # 单域兼容路径：统一标记为 default 域，复用后续合并流程。
            result = self.prefiller.match(
                text,
                max_candidates_per_slot=self.max_candidates_per_slot,
            )
            annotated = ACPrefillResult(
                matches=[self._annotate_domain(item, "default") for item in result.matches],
                slot_matches={
                    slot_name: [self._annotate_domain(item, "default") for item in items]
                    for slot_name, items in result.slot_matches.items()
                },
                slot_candidates={
                    slot_name: [
                        Candidate(
                            entity_id=item.entity_id,
                            name=item.name,
                            score=item.score,
                            meta={**dict(item.meta), "prefill_domain": "default"},
                        )
                        for item in items
                    ]
                    for slot_name, items in result.slot_candidates.items()
                },
            )
            return {"default": annotated}, ["default"]
        return {}, []

    @staticmethod
    def _annotate_domain(item: ACMatch, domain: str) -> ACMatch:
        metadata = dict(item.metadata)
        metadata["prefill_domain"] = domain
        return ACMatch(
            keyword=item.keyword,
            matched_text=item.matched_text,
            start=item.start,
            end=item.end,
            slot=item.slot,
            slot_value=item.slot_value,
            entity_id=item.entity_id,
            entity_name=item.entity_name,
            score=item.score,
            metadata=metadata,
        )

    def _trace_continue(self, ctx: RequestContext, started: float, *, reason: str) -> None:
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason=reason,
                latency_ms=elapsed,
            )
        )
        return None

    @staticmethod
    def _candidate_key(slot_name: str) -> str | None:
        if slot_name == "device_id":
            return "device_candidates"
        if slot_name == "region_id":
            return "region_candidates"
        return None

    @staticmethod
    def _normalize_candidates(items: Any) -> list[Candidate]:
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, Candidate)]

    @staticmethod
    def _merge_candidates(current: list[Candidate], incoming: list[Candidate]) -> list[Candidate]:
        best_by_id: dict[str, Candidate] = {}
        for item in current + incoming:
            entity_id = str(item.entity_id)
            prev = best_by_id.get(entity_id)
            if prev is None or item.score > prev.score:
                best_by_id[entity_id] = item
        merged = list(best_by_id.values())
        merged.sort(key=lambda item: item.score, reverse=True)
        return merged
