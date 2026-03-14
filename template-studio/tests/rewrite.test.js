import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { QueryRewriteStateMachine } from "../lib/rewrite.js";

test("query rewrite whole_word only rewrites standalone token", () => {
  const rewriter = new QueryRewriteStateMachine({
    enabled: true,
    max_passes: 1,
    rules: [
      {
        rule_id: "cpu.typo",
        source: "cup",
        target: "cpu",
        match_mode: "whole_word"
      }
    ]
  });

  const payload = rewriter.rewrite("查询cup和occupancy的告警");

  assert.equal(payload.rewritten_text, "查询cpu和occupancy的告警");
  assert.equal(payload.hits.length, 1);
});

test("query rewrite can hot reload external dictionary", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "rewrite-test-"));
  const dictionaryPath = path.join(tempDir, "rewrite_rules.json");
  fs.writeFileSync(
    dictionaryPath,
    JSON.stringify(
      {
        rules: [
          {
            rule_id: "school.short",
            source: "北二小",
            target: "北京第二小学"
          }
        ]
      },
      null,
      2
    ),
    "utf8"
  );

  const rewriter = new QueryRewriteStateMachine(
    {
      enabled: true,
      max_passes: 1,
      dictionary_path: dictionaryPath,
      reload_on_change: true
    },
    {
      baseDir: tempDir
    }
  );

  const first = rewriter.rewrite("查询北二小的告警");
  assert.equal(first.rewritten_text, "查询北京第二小学的告警");

  fs.writeFileSync(
    dictionaryPath,
    JSON.stringify(
      {
        rules: [
          {
            rule_id: "school.short",
            source: "北二小",
            target: "北京市第二小学"
          }
        ]
      },
      null,
      2
    ),
    "utf8"
  );

  const second = rewriter.rewrite("查询北二小的告警");
  assert.equal(second.rewritten_text, "查询北京市第二小学的告警");
});
