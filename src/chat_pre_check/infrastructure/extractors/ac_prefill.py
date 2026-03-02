from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chat_pre_check.domain.models import Candidate


@dataclass(slots=True)
class PrefillTerm:
    term: str
    slot: str | None = None
    value: Any | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    score: float = 1.0
    aliases: list[str] = field(default_factory=list)
    word_boundary: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ACMatch:
    keyword: str
    matched_text: str
    start: int
    end: int
    slot: str | None
    slot_value: Any | None
    entity_id: str | None
    entity_name: str | None
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolved_slot_value(self) -> Any:
        if self.slot_value is not None:
            return self.slot_value
        if self.entity_id is not None:
            return self.entity_id
        return self.matched_text

    def to_trace(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "matched_text": self.matched_text,
            "start": self.start,
            "end": self.end,
            "slot": self.slot,
            "slot_value": self.resolved_slot_value(),
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "score": self.score,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ACPrefillResult:
    matches: list[ACMatch]
    slot_matches: dict[str, list[ACMatch]]
    slot_candidates: dict[str, list[Candidate]]


@dataclass(slots=True)
class _Pattern:
    keyword: str
    normalized_keyword: str
    term: PrefillTerm
    length: int
    word_boundary: bool


class AhoCorasickAutomaton:
    def __init__(
        self,
        *,
        ignore_case: bool = True,
        default_word_boundary: bool = True,
        max_matches: int = 200,
    ) -> None:
        self.ignore_case = ignore_case
        self.default_word_boundary = default_word_boundary
        self.max_matches = max(1, int(max_matches))
        self._transitions: list[dict[str, int]] = [{}]
        self._fail: list[int] = [0]
        self._outputs: list[list[_Pattern]] = [[]]
        self._built = False

    def add(self, keyword: str, term: PrefillTerm) -> None:
        normalized = self._normalize(keyword)
        if not normalized:
            return
        state = 0
        for ch in normalized:
            next_state = self._transitions[state].get(ch)
            if next_state is None:
                next_state = len(self._transitions)
                self._transitions.append({})
                self._fail.append(0)
                self._outputs.append([])
                self._transitions[state][ch] = next_state
            state = next_state
        self._outputs[state].append(
            _Pattern(
                keyword=keyword,
                normalized_keyword=normalized,
                term=term,
                length=len(normalized),
                word_boundary=self._resolve_word_boundary(term),
            )
        )
        self._built = False

    def build(self) -> None:
        queue: deque[int] = deque()
        for _, state in self._transitions[0].items():
            self._fail[state] = 0
            queue.append(state)

        while queue:
            state = queue.popleft()
            for ch, next_state in self._transitions[state].items():
                queue.append(next_state)
                fail_state = self._fail[state]
                while fail_state and ch not in self._transitions[fail_state]:
                    fail_state = self._fail[fail_state]
                self._fail[next_state] = self._transitions[fail_state].get(ch, 0)
                self._outputs[next_state].extend(self._outputs[self._fail[next_state]])

        self._built = True

    def search(self, text: str) -> list[ACMatch]:
        if not text:
            return []
        if not self._built:
            self.build()

        normalized_text = self._normalize(text)
        state = 0
        matches: list[ACMatch] = []
        for idx, ch in enumerate(normalized_text):
            while state and ch not in self._transitions[state]:
                state = self._fail[state]
            state = self._transitions[state].get(ch, 0)
            outputs = self._outputs[state]
            if not outputs:
                continue
            for pattern in outputs:
                start = idx - pattern.length + 1
                if start < 0:
                    continue
                if pattern.word_boundary and not self._passes_word_boundary(text, start, idx):
                    continue
                matches.append(
                    ACMatch(
                        keyword=pattern.keyword,
                        matched_text=text[start : idx + 1],
                        start=start,
                        end=idx,
                        slot=pattern.term.slot,
                        slot_value=pattern.term.value,
                        entity_id=pattern.term.entity_id,
                        entity_name=pattern.term.entity_name,
                        score=float(pattern.term.score),
                        metadata=dict(pattern.term.metadata),
                    )
                )
                if len(matches) >= self.max_matches:
                    return matches
        return matches

    def _normalize(self, text: str) -> str:
        if self.ignore_case:
            return text.lower()
        return text

    def _resolve_word_boundary(self, term: PrefillTerm) -> bool:
        if term.word_boundary is not None:
            return bool(term.word_boundary)
        # Chinese terms generally do not rely on ASCII boundaries.
        if any(ord(ch) > 127 for ch in term.term):
            return False
        return self.default_word_boundary

    @staticmethod
    def _passes_word_boundary(text: str, start: int, end: int) -> bool:
        left_ok = start == 0 or not _is_ascii_word_char(text[start - 1])
        right_ok = end >= (len(text) - 1) or not _is_ascii_word_char(text[end + 1])
        return left_ok and right_ok


class ACSlotPrefiller:
    def __init__(
        self,
        terms: list[PrefillTerm],
        *,
        ignore_case: bool = True,
        min_term_length: int = 2,
        default_word_boundary: bool = True,
        max_matches: int = 200,
    ) -> None:
        self.min_term_length = max(1, int(min_term_length))
        self.terms = self._deduplicate_terms(terms, ignore_case=ignore_case)
        self.automaton = AhoCorasickAutomaton(
            ignore_case=ignore_case,
            default_word_boundary=default_word_boundary,
            max_matches=max_matches,
        )
        for term in self.terms:
            self.automaton.add(term.term, term)
            for alias in term.aliases:
                self.automaton.add(alias, term)
        self.automaton.build()

    def match(self, text: str, *, max_candidates_per_slot: int = 5) -> ACPrefillResult:
        matches = self.automaton.search(text)
        if not matches:
            return ACPrefillResult(matches=[], slot_matches={}, slot_candidates={})

        slot_buckets: dict[str, dict[str, ACMatch]] = {}
        for hit in matches:
            if not hit.slot:
                continue
            bucket = slot_buckets.setdefault(hit.slot, {})
            dedup_key = self._dedup_key(hit)
            prev = bucket.get(dedup_key)
            if prev is None or self._rank_key(hit) < self._rank_key(prev):
                bucket[dedup_key] = hit

        slot_matches: dict[str, list[ACMatch]] = {}
        slot_candidates: dict[str, list[Candidate]] = {}
        for slot_name, deduped in slot_buckets.items():
            ranked = sorted(deduped.values(), key=self._rank_key)
            if not ranked:
                continue
            slot_matches[slot_name] = ranked
            slot_candidates[slot_name] = [
                Candidate(
                    entity_id=self._candidate_entity_id(item),
                    name=self._candidate_name(item),
                    score=max(0.0, min(1.0, float(item.score))),
                    meta={
                        "source": "ac_prefill",
                        "keyword": item.keyword,
                        "slot": slot_name,
                    },
                )
                for item in ranked[: max(1, int(max_candidates_per_slot))]
            ]

        return ACPrefillResult(
            matches=matches,
            slot_matches=slot_matches,
            slot_candidates=slot_candidates,
        )

    def _deduplicate_terms(
        self,
        terms: list[PrefillTerm],
        *,
        ignore_case: bool,
    ) -> list[PrefillTerm]:
        dedup: dict[str, PrefillTerm] = {}
        for term in terms:
            normalized_term = self._normalize_keyword(term.term, ignore_case=ignore_case)
            if len(normalized_term) < self.min_term_length:
                continue
            normalized_aliases = []
            for alias in term.aliases:
                normalized_alias = self._normalize_keyword(alias, ignore_case=ignore_case)
                if len(normalized_alias) < self.min_term_length:
                    continue
                normalized_aliases.append(alias.strip())
            clean = PrefillTerm(
                term=term.term.strip(),
                slot=term.slot,
                value=term.value,
                entity_id=term.entity_id,
                entity_name=term.entity_name,
                score=max(0.0, min(1.0, float(term.score))),
                aliases=sorted(list(dict.fromkeys([alias for alias in normalized_aliases if alias]))),
                word_boundary=term.word_boundary,
                metadata=dict(term.metadata),
            )
            key = self._term_key(clean, ignore_case=ignore_case)
            prev = dedup.get(key)
            if prev is None or clean.score > prev.score:
                dedup[key] = clean
        return list(dedup.values())

    @staticmethod
    def _normalize_keyword(keyword: str, *, ignore_case: bool) -> str:
        text = str(keyword).strip()
        if ignore_case:
            text = text.lower()
        return text

    @staticmethod
    def _term_key(term: PrefillTerm, *, ignore_case: bool) -> str:
        normalized = ACSlotPrefiller._normalize_keyword(term.term, ignore_case=ignore_case)
        return f"{term.slot}|{term.value}|{term.entity_id}|{normalized}"

    @staticmethod
    def _rank_key(hit: ACMatch) -> tuple[float, int, int]:
        length = hit.end - hit.start + 1
        # Higher score first, then longer term, then earlier position.
        return (-float(hit.score), -length, hit.start)

    @staticmethod
    def _dedup_key(hit: ACMatch) -> str:
        value = hit.resolved_slot_value()
        return f"{hit.slot}:{value}"

    @staticmethod
    def _candidate_entity_id(hit: ACMatch) -> str:
        if hit.entity_id:
            return str(hit.entity_id)
        value = hit.resolved_slot_value()
        return str(value)

    @staticmethod
    def _candidate_name(hit: ACMatch) -> str:
        if hit.entity_name:
            return str(hit.entity_name)
        return hit.matched_text


def build_slot_prefiller(
    *,
    config_dir: str | Path,
    prefill_cfg: dict[str, Any] | None,
) -> ACSlotPrefiller | None:
    cfg = prefill_cfg or {}
    if not bool(cfg.get("enabled", False)):
        return None

    raw_terms = _resolve_raw_terms(config_dir=Path(config_dir), prefill_cfg=cfg)
    terms = _parse_prefill_terms(raw_terms)
    if not terms:
        return None
    return ACSlotPrefiller(
        terms,
        ignore_case=bool(cfg.get("ignore_case", True)),
        min_term_length=max(1, int(cfg.get("min_term_length", 2))),
        default_word_boundary=bool(cfg.get("default_word_boundary", True)),
        max_matches=max(1, int(cfg.get("max_matches", 200))),
    )


def _resolve_raw_terms(*, config_dir: Path, prefill_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    inline_terms = prefill_cfg.get("terms")
    if isinstance(inline_terms, list):
        return [item for item in inline_terms if isinstance(item, dict)]

    dictionary_file = str(prefill_cfg.get("dictionary_file", "ac_terms.json"))
    dictionary_path = Path(dictionary_file)
    if not dictionary_path.is_absolute():
        dictionary_path = config_dir / dictionary_path
    if not dictionary_path.exists():
        return []

    with dictionary_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("terms", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _parse_prefill_terms(raw_terms: list[dict[str, Any]]) -> list[PrefillTerm]:
    terms: list[PrefillTerm] = []
    for raw in raw_terms:
        keyword = str(raw.get("term", "")).strip()
        if not keyword:
            continue
        aliases = raw.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = []
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        term = PrefillTerm(
            term=keyword,
            slot=_to_optional_str(raw.get("slot", raw.get("slot_name"))),
            value=raw.get("value", raw.get("slot_value")),
            entity_id=_to_optional_str(raw.get("entity_id")),
            entity_name=_to_optional_str(raw.get("entity_name")),
            score=_to_score(raw.get("score", 1.0)),
            aliases=[str(alias) for alias in aliases if str(alias).strip()],
            word_boundary=_to_optional_bool(raw.get("word_boundary")),
            metadata=metadata,
        )
        terms.append(term)
    return terms


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _to_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, score))


def _to_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _is_ascii_word_char(ch: str) -> bool:
    if not ch:
        return False
    code = ord(ch)
    if code >= 128:
        return False
    return ch.isalnum() or ch == "_"
