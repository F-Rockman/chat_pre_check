from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chat_pre_check.domain.models import Candidate


# AC 词典中的标准词条定义（来自配置内联或 ac_terms.json）。
@dataclass(slots=True)
class PrefillTerm:
    term: str
    domain: str = "default"
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
    """AC 自动机：用于在一段文本中一次扫描完成多关键词匹配。"""

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
        # BFS 构建 fail 指针，并将失配状态的输出合并到当前状态。
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
        # 单次线性扫描：失配时沿 fail 回退，命中时输出对应模式。
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
        # 中文词通常不依赖 ASCII 边界，默认关闭边界约束以提升召回。
        if any(ord(ch) > 127 for ch in term.term):
            return False
        return self.default_word_boundary

    @staticmethod
    def _passes_word_boundary(text: str, start: int, end: int) -> bool:
        left_ok = start == 0 or not _is_ascii_word_char(text[start - 1])
        right_ok = end >= (len(text) - 1) or not _is_ascii_word_char(text[end + 1])
        return left_ok and right_ok


class ACSlotPrefiller:
    """单域 AC 预提参器：负责匹配、去重、排序，并产出候选槽位值。"""

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

        # 先按槽位分桶，再用“槽位+值”去重，保留排名更高的命中。
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
                domain=str(term.domain or "default").strip() or "default",
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
        domain = str(term.domain or "default").strip() or "default"
        return f"{domain}|{term.slot}|{term.value}|{term.entity_id}|{normalized}"

    @staticmethod
    def _rank_key(hit: ACMatch) -> tuple[float, int, int]:
        length = hit.end - hit.start + 1
        # 排序优先级：分数更高 > 词更长 > 位置更靠前。
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
) -> "ACDomainPrefillManager | None":
    cfg = prefill_cfg or {}
    if not bool(cfg.get("enabled", False)):
        return None

    # 支持两种词典来源：配置内联 terms 或 dictionary_file 外部文件。
    raw_terms = _resolve_raw_terms(config_dir=Path(config_dir), prefill_cfg=cfg)
    terms = _parse_prefill_terms(raw_terms)
    if not terms:
        return None
    return ACDomainPrefillManager.from_terms(
        terms=terms,
        ignore_case=bool(cfg.get("ignore_case", True)),
        min_term_length=max(1, int(cfg.get("min_term_length", 2))),
        default_word_boundary=bool(cfg.get("default_word_boundary", True)),
        max_matches=max(1, int(cfg.get("max_matches", 200))),
        domain_priority=_to_domain_priority(cfg.get("domain_priority")),
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
    return _flatten_raw_terms(payload)


def _flatten_raw_terms(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    terms: list[dict[str, Any]] = []
    root_terms = payload.get("terms", [])
    if isinstance(root_terms, list):
        terms.extend(item for item in root_terms if isinstance(item, dict))
    domain_groups = payload.get("domains", {})
    if isinstance(domain_groups, dict):
        for domain_name, domain_terms in domain_groups.items():
            if not isinstance(domain_terms, list):
                continue
            for raw in domain_terms:
                if not isinstance(raw, dict):
                    continue
                item = dict(raw)
                item.setdefault("domain", str(domain_name))
                terms.append(item)
    return terms


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
            domain=_to_domain(raw.get("domain"), metadata),
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


def _to_domain(value: Any, metadata: dict[str, Any]) -> str:
    direct = _to_optional_str(value)
    if direct:
        return direct
    meta_domain = _to_optional_str(metadata.get("domain"))
    if meta_domain:
        return meta_domain
    return "default"


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


def _to_domain_priority(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    priorities: dict[str, float] = {}
    for key, raw in value.items():
        domain = str(key).strip()
        if not domain:
            continue
        try:
            priorities[domain] = float(raw)
        except (TypeError, ValueError):
            continue
    return priorities


class ACDomainPrefillManager:
    """多域预提参管理器：为不同业务域维护独立 AC 实例并统一仲裁结果。"""

    def __init__(
        self,
        *,
        domain_prefillers: dict[str, ACSlotPrefiller],
        domain_priority: dict[str, float] | None = None,
    ) -> None:
        self.domain_prefillers = dict(domain_prefillers)
        self.domain_priority = domain_priority or {}

    @classmethod
    def from_terms(
        cls,
        *,
        terms: list[PrefillTerm],
        ignore_case: bool,
        min_term_length: int,
        default_word_boundary: bool,
        max_matches: int,
        domain_priority: dict[str, float] | None = None,
    ) -> "ACDomainPrefillManager":
        grouped: dict[str, list[PrefillTerm]] = {}
        for term in terms:
            domain = str(term.domain or "default").strip() or "default"
            grouped.setdefault(domain, []).append(term)
        prefiller_map: dict[str, ACSlotPrefiller] = {}
        for domain, items in grouped.items():
            prefiller_map[domain] = ACSlotPrefiller(
                items,
                ignore_case=ignore_case,
                min_term_length=min_term_length,
                default_word_boundary=default_word_boundary,
                max_matches=max_matches,
            )
        return cls(domain_prefillers=prefiller_map, domain_priority=domain_priority)

    def available_domains(self) -> list[str]:
        domains = list(self.domain_prefillers.keys())
        domains.sort(key=lambda item: (-self.domain_priority.get(item, 0.0), item))
        return domains

    def match_by_domain(
        self,
        text: str,
        *,
        domains: list[str] | None = None,
        max_candidates_per_slot: int = 5,
    ) -> dict[str, ACPrefillResult]:
        selected = self._select_domains(domains)
        results: dict[str, ACPrefillResult] = {}
        for domain in selected:
            prefiller = self.domain_prefillers.get(domain)
            if prefiller is None:
                continue
            result = prefiller.match(text, max_candidates_per_slot=max_candidates_per_slot)
            results[domain] = self._attach_domain(domain, result)
        return results

    def match(
        self,
        text: str,
        *,
        domains: list[str] | None = None,
        max_candidates_per_slot: int = 5,
    ) -> ACPrefillResult:
        by_domain = self.match_by_domain(
            text,
            domains=domains,
            max_candidates_per_slot=max_candidates_per_slot,
        )
        return self._merge_results(by_domain, max_candidates_per_slot=max_candidates_per_slot)

    def _select_domains(self, domains: list[str] | None) -> list[str]:
        if not domains:
            return self.available_domains()
        selected: list[str] = []
        seen: set[str] = set()
        for item in domains:
            domain = str(item).strip()
            if not domain or domain in seen:
                continue
            seen.add(domain)
            if domain in self.domain_prefillers:
                selected.append(domain)
        return selected

    def _attach_domain(self, domain: str, result: ACPrefillResult) -> ACPrefillResult:
        cloned_matches = [self._clone_match(domain, item) for item in result.matches]
        slot_matches: dict[str, list[ACMatch]] = {}
        for slot_name, items in result.slot_matches.items():
            slot_matches[slot_name] = [self._clone_match(domain, item) for item in items]
        slot_candidates: dict[str, list[Candidate]] = {}
        for slot_name, items in result.slot_candidates.items():
            slot_candidates[slot_name] = []
            for candidate in items:
                meta = dict(candidate.meta)
                meta["prefill_domain"] = domain
                slot_candidates[slot_name].append(
                    Candidate(
                        entity_id=candidate.entity_id,
                        name=candidate.name,
                        score=candidate.score,
                        meta=meta,
                    )
                )
        return ACPrefillResult(
            matches=cloned_matches,
            slot_matches=slot_matches,
            slot_candidates=slot_candidates,
        )

    def _merge_results(
        self,
        by_domain: dict[str, ACPrefillResult],
        *,
        max_candidates_per_slot: int,
    ) -> ACPrefillResult:
        all_matches: list[ACMatch] = []
        slot_map: dict[str, dict[str, ACMatch]] = {}
        for domain, result in by_domain.items():
            all_matches.extend(result.matches)
            for slot_name, items in result.slot_matches.items():
                bucket = slot_map.setdefault(slot_name, {})
                for item in items:
                    key = f"{slot_name}:{item.resolved_slot_value()}"
                    prev = bucket.get(key)
                    # 跨域冲突时按统一排序键保留更优命中。
                    if prev is None or self._rank_key(item) < self._rank_key(prev):
                        bucket[key] = item

        slot_matches: dict[str, list[ACMatch]] = {}
        slot_candidates: dict[str, list[Candidate]] = {}
        for slot_name, dedup in slot_map.items():
            ranked = sorted(dedup.values(), key=self._rank_key)
            if not ranked:
                continue
            slot_matches[slot_name] = ranked
            slot_candidates[slot_name] = [
                Candidate(
                    entity_id=(
                        str(item.entity_id)
                        if item.entity_id is not None
                        else str(item.resolved_slot_value())
                    ),
                    name=item.entity_name or item.matched_text,
                    score=max(0.0, min(1.0, float(item.score))),
                    meta={
                        "source": "ac_prefill",
                        "keyword": item.keyword,
                        "slot": slot_name,
                        "prefill_domain": str(item.metadata.get("prefill_domain", "")),
                    },
                )
                for item in ranked[: max(1, int(max_candidates_per_slot))]
            ]
        return ACPrefillResult(
            matches=all_matches,
            slot_matches=slot_matches,
            slot_candidates=slot_candidates,
        )

    @staticmethod
    def _clone_match(domain: str, item: ACMatch) -> ACMatch:
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

    def _rank_key(self, item: ACMatch) -> tuple[float, float, int, int]:
        domain = str(item.metadata.get("prefill_domain", ""))
        priority = float(self.domain_priority.get(domain, 0.0))
        length = item.end - item.start + 1
        # 排序优先级：命中分数 > 域优先级 > 词长 > 位置。
        return (-float(item.score), -priority, -length, item.start)
