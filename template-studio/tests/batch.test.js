import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { batchGenerateTemplates, evaluateBatchMatch, parseBatchSource, summarizeBatchMatches } from "../lib/batch.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, "..", "..");

test("parseBatchSource supports evaluation corpus json", async () => {
  const payload = await fs.readFile(path.join(ROOT, "tests", "fixtures", "evaluation_cases.json"), "utf8");
  const parsed = parseBatchSource(payload, "evaluation_cases.json");

  assert.equal(parsed.format, "evaluation_cases");
  assert.ok(parsed.items.length > 10);
  assert.equal(parsed.items[0].expected_status, "matched");
  assert.equal(parsed.items[0].expected_template_id, "alarm.interface.error.topn");
});

test("parseBatchSource supports plain text and strips comments", () => {
  const parsed = parseBatchSource(
    `
# comment
查询最近cpu大于80的设备列表

查询近24小时接口错误包告警前十
    `,
    "queries.txt"
  );

  assert.equal(parsed.format, "text");
  assert.equal(parsed.items.length, 2);
  assert.equal(parsed.items[0].text, "查询最近cpu大于80的设备列表");
});

test("evaluateBatchMatch supports not_full_match expectations", () => {
  const evaluation = evaluateBatchMatch(
    {
      text: "给我一份cpu报告",
      expected_not_full_match: true
    },
    {
      template_id: -1,
      status: "unmatched"
    }
  );

  assert.equal(evaluation.evaluated, true);
  assert.equal(evaluation.pass, true);
});

test("batchGenerateTemplates aggregates success and failure counts", async () => {
  const output = await batchGenerateTemplates(
    [
      { id: "1", text: "查询最近cpu大于80的设备列表" },
      { id: "2", text: " " }
    ],
    async (item) => {
      if (!item.text.trim()) {
        throw new Error("empty");
      }
      return {
        analysis: {
          intent: item.text
        },
        template: {
          template_id: "device.cpu.over.list"
        }
      };
    }
  );

  assert.equal(output.success_count, 1);
  assert.equal(output.failure_count, 1);
  assert.equal(output.results[0].ok, true);
  assert.equal(output.results[1].ok, false);
});

test("summarizeBatchMatches computes evaluation pass rate", () => {
  const summary = summarizeBatchMatches([
    {
      result: { status: "matched" },
      evaluation: { evaluated: true, pass: true }
    },
    {
      result: { status: "partial" },
      evaluation: { evaluated: true, pass: false }
    },
    {
      result: { status: "unmatched" },
      evaluation: { evaluated: false, pass: null }
    }
  ]);

  assert.equal(summary.total, 3);
  assert.equal(summary.pass_count, 1);
  assert.equal(summary.fail_count, 1);
  assert.equal(summary.evaluated_count, 2);
  assert.equal(summary.pass_rate, 0.5);
});
