import fs from "node:fs";
import path from "node:path";

import { normalizeText } from "./utils.js";

class TrieNode {
  constructor() {
    this.children = new Map();
    this.rule = null;
  }
}

export class QueryRewriteStateMachine {
  constructor(settings = {}, options = {}) {
    this.settings = {
      enabled: Boolean(settings.enabled),
      max_passes: Math.max(1, Number(settings.max_passes ?? 1)),
      dictionary_path: settings.dictionary_path ? String(settings.dictionary_path) : "",
      reload_on_change: settings.reload_on_change ?? true,
      rules: Array.isArray(settings.rules) ? settings.rules : []
    };
    this.baseDir = String(options.baseDir || process.cwd());
    this.inlineRules = this.settings.rules
      .map((rule, index) => this.normalizeRule(rule, index + 1))
      .filter(Boolean);
    this.externalRules = [];
    this.dictionaryPath = this.settings.dictionary_path
      ? path.resolve(this.baseDir, this.settings.dictionary_path)
      : "";
    this.dictionarySignature = "";
    this.root = new TrieNode();
    this.rebuildRules({ force: true });
  }

  rewrite(inputText) {
    return this.rewriteNormalized(normalizeText(inputText));
  }

  rewriteNormalized(normalizedText) {
    const originalText = normalizeText(normalizedText);
    this.rebuildRules();
    if (!this.settings.enabled || !originalText || (!this.inlineRules.length && !this.externalRules.length)) {
      return {
        original_text: originalText,
        rewritten_text: originalText,
        changed: false,
        pass_count: 0,
        hits: []
      };
    }
    let currentText = originalText;
    const seen = new Set([currentText]);
    const hits = [];
    let passCount = 0;
    for (let passIndex = 1; passIndex <= this.settings.max_passes; passIndex += 1) {
      const step = this.rewriteOnce(currentText, passIndex);
      if (!step.hits.length || step.rewrittenText === currentText) {
        break;
      }
      hits.push(...step.hits);
      passCount = passIndex;
      currentText = step.rewrittenText;
      if (seen.has(currentText)) {
        break;
      }
      seen.add(currentText);
    }
    return {
      original_text: originalText,
      rewritten_text: currentText,
      changed: originalText !== currentText,
      pass_count: passCount,
      hits
    };
  }

  buildTrie(rules) {
    this.root = new TrieNode();
    for (const [index, rawRule] of rules.entries()) {
      const source = normalizeText(rawRule.source || "");
      const target = normalizeText(rawRule.target || "");
      if (!source || !target) {
        continue;
      }
      let node = this.root;
      for (const char of source) {
        if (!node.children.has(char)) {
          node.children.set(char, new TrieNode());
        }
        node = node.children.get(char);
      }
      if (!node.rule) {
        node.rule = {
          rule_id: String(rawRule.rule_id || `rewrite_rule_${index + 1}`),
          source,
          target,
          match_mode: String(rawRule.match_mode || "substring")
        };
      }
    }
  }

  rewriteOnce(text, passIndex) {
    const output = [];
    const hits = [];
    let cursor = 0;
    while (cursor < text.length) {
      const match = this.longestMatch(text, cursor);
      if (!match.rule) {
        output.push(text[cursor]);
        cursor += 1;
        continue;
      }
      output.push(match.rule.target);
      hits.push({
        pass_index: passIndex,
        rule_id: match.rule.rule_id,
        source: match.rule.source,
        target: match.rule.target
      });
      cursor = match.end;
    }
    return {
      rewrittenText: normalizeText(output.join("")),
      hits
    };
  }

  longestMatch(text, start) {
    let node = this.root;
    let cursor = start;
    let matchedRule = null;
    let matchedEnd = start;
    while (cursor < text.length) {
      const nextNode = node.children.get(text[cursor]);
      if (!nextNode) {
        break;
      }
      node = nextNode;
      cursor += 1;
      if (node.rule && this.boundaryMatches(text, start, cursor, node.rule)) {
        matchedRule = node.rule;
        matchedEnd = cursor;
      }
    }
    return {
      rule: matchedRule,
      end: matchedEnd
    };
  }

  rebuildRules({ force = false } = {}) {
    if (!this.dictionaryPath) {
      if (force) {
        this.buildTrie(this.inlineRules);
      }
      return;
    }
    if (!force && !this.settings.reload_on_change) {
      return;
    }
    const loaded = this.loadExternalRules();
    if (loaded !== null && (force || loaded.signature !== this.dictionarySignature)) {
      this.externalRules = loaded.rules;
      this.dictionarySignature = loaded.signature;
      this.buildTrie([...this.inlineRules, ...this.externalRules]);
    }
  }

  loadExternalRules() {
    if (!this.dictionaryPath) {
      return [];
    }
    let payload;
    try {
      const text = fs.readFileSync(this.dictionaryPath, "utf8");
      payload = JSON.parse(text);
      return {
        signature: text,
        rules: this.normalizeExternalRules(payload)
      };
    } catch (error) {
      if (error && error.code === "ENOENT") {
        return {
          signature: "",
          rules: []
        };
      }
      if (error instanceof SyntaxError) {
        return this.externalRules.length ? null : { signature: "", rules: [] };
      }
      return this.externalRules.length ? null : { signature: "", rules: [] };
    }
  }

  normalizeExternalRules(payload) {
    const rawRules = Array.isArray(payload) ? payload : Array.isArray(payload?.rules) ? payload.rules : [];
    return rawRules
      .map((rule, index) => this.normalizeRule(rule, index + 1))
      .filter(Boolean);
  }

  normalizeRule(rule, index) {
    const source = normalizeText(rule?.source || "");
    const target = normalizeText(rule?.target || "");
    if (!source || !target) {
      return null;
    }
    return {
      rule_id: String(rule?.rule_id || `rewrite_rule_${index}`),
      source,
      target,
      match_mode: String(rule?.match_mode || "substring")
    };
  }

  boundaryMatches(text, start, end, rule) {
    if (String(rule?.match_mode || "substring").toLowerCase() !== "whole_word") {
      return true;
    }
    if (![...String(rule.source || "")].some((char) => this.isTokenChar(char))) {
      return true;
    }
    const prevChar = start > 0 ? text[start - 1] : "";
    const nextChar = end < text.length ? text[end] : "";
    return !this.isTokenChar(prevChar) && !this.isTokenChar(nextChar);
  }

  isTokenChar(char) {
    return Boolean(char) && (/^[a-z0-9_.-]$/i.test(char));
  }
}
