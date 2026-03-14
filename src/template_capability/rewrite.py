from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from template_capability.extractors import normalize_text
from template_capability.models import QueryRewriteRule, QueryRewriteSettings


@dataclass(slots=True)
class RewriteHit:
    """一次具体命中的改写记录。"""

    pass_index: int
    rule_id: str
    source: str
    target: str

    def to_dict(self) -> dict[str, object]:
        return {
            "pass_index": self.pass_index,
            "rule_id": self.rule_id,
            "source": self.source,
            "target": self.target,
        }


@dataclass(slots=True)
class RewriteResult:
    """一次 query 改写的完整结果。"""

    original_text: str
    rewritten_text: str
    pass_count: int
    hits: list[RewriteHit] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.original_text != self.rewritten_text

    def to_dict(self) -> dict[str, object]:
        return {
            "original_text": self.original_text,
            "rewritten_text": self.rewritten_text,
            "changed": self.changed,
            "pass_count": self.pass_count,
            "hits": [item.to_dict() for item in self.hits],
        }


@dataclass(slots=True)
class _TrieNode:
    children: dict[str, "_TrieNode"] = field(default_factory=dict)
    rule: QueryRewriteRule | None = None


class QueryRewriteStateMachine:
    """基于 Trie 状态机的 query 改写器。

    这层做的是短语级 rewrite，不是模板判断。
    目标是把 query 里的行业简称、别名、黑话统一改到模板更稳定的说法。
    """

    def __init__(self, settings: QueryRewriteSettings) -> None:
        self.settings = settings
        self.inline_rules = [self._normalize_rule(rule, index + 1) for index, rule in enumerate(settings.rules)]
        self.inline_rules = [rule for rule in self.inline_rules if rule is not None]
        self.dictionary_path = Path(settings.dictionary_path).resolve() if settings.dictionary_path else None
        self.external_rules: list[QueryRewriteRule] = []
        self._dictionary_signature: str = ""
        self.root = _TrieNode()
        self._rebuild_rules(force=True)

    def rewrite(self, text: str) -> RewriteResult:
        return self.rewrite_normalized(normalize_text(text))

    def rewrite_normalized(self, normalized_text: str) -> RewriteResult:
        current = normalize_text(normalized_text)
        self._rebuild_rules()
        if not self.settings.enabled or not current or (not self.inline_rules and not self.external_rules):
            return RewriteResult(
                original_text=current,
                rewritten_text=current,
                pass_count=0,
                hits=[],
            )
        original = current
        all_hits: list[RewriteHit] = []
        seen = {current}
        pass_count = 0
        for pass_index in range(1, max(1, self.settings.max_passes) + 1):
            rewritten, hits = self._rewrite_once(current, pass_index)
            if not hits or rewritten == current:
                break
            all_hits.extend(hits)
            pass_count = pass_index
            current = rewritten
            if current in seen:
                break
            seen.add(current)
        return RewriteResult(
            original_text=original,
            rewritten_text=current,
            pass_count=pass_count,
            hits=all_hits,
        )

    def _build_trie(self, rules: list[QueryRewriteRule]) -> None:
        self.root = _TrieNode()
        for index, rule in enumerate(rules, start=1):
            source = normalize_text(rule.source)
            target = normalize_text(rule.target)
            if not source or not target:
                continue
            node = self.root
            for char in source:
                node = node.children.setdefault(char, _TrieNode())
            if node.rule is None:
                node.rule = QueryRewriteRule(
                    source=source,
                    target=target,
                    rule_id=rule.rule_id or f"rewrite_rule_{index}",
                    match_mode=rule.match_mode or "substring",
                )

    def _rewrite_once(self, text: str, pass_index: int) -> tuple[str, list[RewriteHit]]:
        output: list[str] = []
        hits: list[RewriteHit] = []
        cursor = 0
        while cursor < len(text):
            matched_rule, next_cursor = self._longest_match(text, cursor)
            if matched_rule is None:
                output.append(text[cursor])
                cursor += 1
                continue
            output.append(matched_rule.target)
            hits.append(
                RewriteHit(
                    pass_index=pass_index,
                    rule_id=matched_rule.rule_id,
                    source=matched_rule.source,
                    target=matched_rule.target,
                )
            )
            cursor = next_cursor
        return normalize_text("".join(output)), hits

    def _longest_match(self, text: str, start: int) -> tuple[QueryRewriteRule | None, int]:
        node = self.root
        cursor = start
        matched_rule: QueryRewriteRule | None = None
        matched_end = start
        while cursor < len(text):
            next_node = node.children.get(text[cursor])
            if next_node is None:
                break
            node = next_node
            cursor += 1
            if node.rule is not None:
                if self._boundary_matches(text, start, cursor, node.rule):
                    matched_rule = node.rule
                    matched_end = cursor
        return matched_rule, matched_end

    def _rebuild_rules(self, *, force: bool = False) -> None:
        if not self.dictionary_path:
            if force:
                self._build_trie(self.inline_rules)
            return
        if not force and not self.settings.reload_on_change:
            return
        loaded = self._load_external_rules()
        if loaded is not None and (force or loaded["signature"] != self._dictionary_signature):
            self.external_rules = loaded["rules"]
            self._dictionary_signature = loaded["signature"]
            self._build_trie([*self.inline_rules, *self.external_rules])

    def _load_external_rules(self) -> dict[str, object] | None:
        if self.dictionary_path is None:
            return {"signature": "", "rules": []}
        try:
            raw_text = self.dictionary_path.read_text(encoding="utf-8")
            payload = json.loads(raw_text)
        except FileNotFoundError:
            return {"signature": "", "rules": []}
        except OSError:
            return {"signature": "", "rules": []} if not self.external_rules else None
        except json.JSONDecodeError:
            return None if self.external_rules else {"signature": "", "rules": []}
        if isinstance(payload, dict):
            raw_rules = payload.get("rules", [])
        elif isinstance(payload, list):
            raw_rules = payload
        else:
            raw_rules = []
        rules = [
            self._normalize_rule(item, index + 1)
            for index, item in enumerate(raw_rules)
            if isinstance(item, dict)
        ]
        return {
            "signature": raw_text,
            "rules": [rule for rule in rules if rule is not None],
        }

    def _normalize_rule(self, rule: QueryRewriteRule | dict[str, object], index: int) -> QueryRewriteRule | None:
        if isinstance(rule, QueryRewriteRule):
            source = normalize_text(rule.source)
            target = normalize_text(rule.target)
            rule_id = rule.rule_id or f"rewrite_rule_{index}"
            match_mode = rule.match_mode or "substring"
        else:
            source = normalize_text(str(rule.get("source", "")))
            target = normalize_text(str(rule.get("target", "")))
            rule_id = str(rule.get("rule_id", f"rewrite_rule_{index}"))
            match_mode = str(rule.get("match_mode", "substring") or "substring")
        if not source or not target:
            return None
        return QueryRewriteRule(
            source=source,
            target=target,
            rule_id=rule_id,
            match_mode=match_mode,
        )

    def _boundary_matches(
        self,
        text: str,
        start: int,
        end: int,
        rule: QueryRewriteRule,
    ) -> bool:
        if (rule.match_mode or "substring").lower() != "whole_word":
            return True
        # whole_word 主要为英文、数字、设备编码等有明确 token 边界的表达设计。
        if not any(self._is_token_char(char) for char in rule.source):
            return True
        prev_char = text[start - 1] if start > 0 else ""
        next_char = text[end] if end < len(text) else ""
        return not self._is_token_char(prev_char) and not self._is_token_char(next_char)

    def _is_token_char(self, char: str) -> bool:
        return bool(char) and (
            (char.isascii() and char.isalnum())
            or char in {"_", "-", "."}
        )
