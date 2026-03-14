import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { TemplateMatcher } from "../lib/matcher.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, "..", "..");

async function loadConfig() {
  const payload = await fs.readFile(path.join(ROOT, "configs", "templates.json"), "utf8");
  return JSON.parse(payload);
}

test("node matcher matches a known topn template", async () => {
  const matcher = new TemplateMatcher(await loadConfig());
  const result = matcher.match("近24小时接口错误包告警Top10");

  assert.equal(result.template_id, "alarm.interface.error.topn");
  assert.equal(result.status, "matched");
  assert.equal(result.slots.topn, 10);
});

test("node matcher can isolate current template scope", async () => {
  const matcher = new TemplateMatcher(await loadConfig());
  const result = matcher.match("查询最近cpu大于80且内存大于70的设备列表", {
    templateIds: ["device.cpu.memory.over.list"]
  });

  assert.equal(result.template_id, "device.cpu.memory.over.list");
  assert.equal(result.status, "matched");
});

test("node matcher rejects blocked intents", async () => {
  const matcher = new TemplateMatcher(await loadConfig());
  const result = matcher.match("帮我分析最近cpu异常原因");

  assert.equal(result.template_id, -1);
  assert.equal(result.status, "unmatched");
});

test("node matcher applies query rewrite before matching", () => {
  const matcher = new TemplateMatcher({
    matcher: {
      match_threshold: 0.4,
      ambiguity_margin: 0.03,
      recall_top_k: 10,
      weights: {
        lexical: 0.6,
        sample: 0.1,
        vector: 0.1,
        fusion: 0.1,
        slot_fit: 0.05,
        constraint: 0.05,
        structure: 0
      }
    },
    query_rewrite: {
      enabled: true,
      max_passes: 1,
      rules: [
        {
          rule_id: "school.short",
          source: "北二小",
          target: "北京第二小学"
        }
      ]
    },
    templates: [
      {
        template_id: "school.alarm.count",
        query_mode: "metric_query",
        description: "查询北京第二小学告警数量",
        utterances: ["查询北京第二小学的告警数量"],
        required_slots: [],
        optional_slots: [],
        must_terms: [["北京第二小学"], ["告警"]],
        negative_terms: [],
        slot_constraints: {},
        slot_extractors: {},
        llm_slot_extraction: {
          enabled: false,
          slots: [],
          instructions: ""
        },
        metadata: {}
      }
    ]
  });

  const result = matcher.match("查询北二小的告警");

  assert.equal(result.template_id, "school.alarm.count");
  assert.equal(result.trace.rewrite_trace.changed, true);
  assert.equal(result.trace.rewrite_trace.rewritten_text, "查询北京第二小学的告警");
});
