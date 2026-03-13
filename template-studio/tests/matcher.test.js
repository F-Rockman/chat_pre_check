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
