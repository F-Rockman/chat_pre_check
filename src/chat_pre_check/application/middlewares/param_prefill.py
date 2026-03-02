from __future__ import annotations

import time
from typing import Any

from chat_pre_check.domain.models import Candidate, RequestContext, RouteDecision, TraceStep
from chat_pre_check.infrastructure.extractors.ac_prefill import ACSlotPrefiller


class ParamPrefillMiddleware:
    name = "param_prefill"

    def __init__(
        self,
        *,
        prefiller: ACSlotPrefiller | None,
        enabled: bool = False,
        auto_commit: bool = True,
        commit_score: float = 0.95,
        min_gap: float = 0.05,
        max_candidates_per_slot: int = 3,
        max_trace_matches: int = 10,
    ) -> None:
        self.prefiller = prefiller
        self.enabled = bool(enabled and prefiller is not None)
        self.auto_commit = bool(auto_commit)
        self.commit_score = float(commit_score)
        self.min_gap = float(min_gap)
        self.max_candidates_per_slot = max(1, int(max_candidates_per_slot))
        self.max_trace_matches = max(1, int(max_trace_matches))

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        if not self.enabled:
            return self._trace_continue(ctx, started, reason="prefill_disabled")

        text = ctx.norm_text or ctx.input_text
        result = self.prefiller.match(
            text,
            max_candidates_per_slot=self.max_candidates_per_slot,
        )
        if not result.matches:
            return self._trace_continue(ctx, started, reason="prefill_no_match")

        committed_slots: dict[str, Any] = {}
        if self.auto_commit:
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
            existing = self._normalize_candidates(ctx.entities.get(key, []))
            merged = self._merge_candidates(existing, candidates)
            ctx.entities[key] = merged
            merged_candidates += len(merged)

        ctx.entities["ac_prefill_matches"] = [
            match.to_trace() for match in result.matches[: self.max_trace_matches]
        ]
        ctx.entities["ac_prefill_slots"] = sorted(result.slot_matches.keys())
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
                },
            )
        )
        return None

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
