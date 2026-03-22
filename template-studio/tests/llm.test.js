import assert from "node:assert/strict";
import test from "node:test";

import { buildGenerationPrompt, generateTemplateFromSentence, parseModelJsonObject } from "../lib/llm.js";

test("parseModelJsonObject strips think tags and parses JSON blocks", () => {
  const payload = parseModelJsonObject(`
<think>
先分析一下模板结构
</think>
\`\`\`json
{
  "analysis": {
    "intent": "查询CPU异常设备列表"
  },
  "template": {
    "template_id": "device.cpu.over.list",
    "query_mode": "metric_query"
  }
}
\`\`\`
  `);

  assert.equal(payload?.analysis?.intent, "查询CPU异常设备列表");
  assert.equal(payload?.template?.template_id, "device.cpu.over.list");
});

test("generateTemplateFromSentence accepts OpenAI-compatible content with think prefix", async () => {
  const fakeClient = {
    chat: {
      completions: {
        async create() {
          return {
            choices: [
              {
                message: {
                  content: `<think>先判断模板形态</think>{
  "analysis": {
    "intent": "查询指定网络设备CPU利用率最大值",
    "entity": "network_device",
    "metric": "cpu_usage",
    "query_operator": "aggregate",
    "template_strategy": "按查询形态拆成聚合值模板，把设备定位方式下沉为槽位",
    "required_slots": ["time_range", "selector_type", "selector_value", "metric", "aggregation"],
    "optional_slots": ["entity_type"],
    "notes": ["selector_value 用带前缀锚点的 regex 抽取"],
    "design_rationale": ["趋势和聚合值的结果形态不同，因此先拆模板边界。"]
  },
  "template": {
    "template_id": "network.device.resource.aggregate.by_selector",
    "query_mode": "metric_query",
    "description": "查询指定网络设备CPU或内存利用率的最大值最小值平均值",
    "utterances": [
      "查询近24小时ip为10.1.1.1的交换机cpu利用率最大值",
      "昨天mac为aa:bb:cc:dd:ee:ff的路由器内存利用率平均值",
      "最近7天名称为core-sw-01的网络设备cpu最小值",
      "查询近24小时ip为10.1.1.1的交换机cpu平均值",
      "昨天名称为core-sw-01的网络设备cpu最大值"
    ],
    "required_slots": ["time_range", "selector_type", "selector_value", "metric", "aggregation"],
    "optional_slots": ["entity_type"],
    "must_terms": [["ip", "mac", "名称"], ["cpu", "内存"], ["最大", "最小", "平均"]],
    "negative_terms": ["原因", "根因", "报告", "总结", "预测", "趋势"],
    "slot_constraints": {
      "metric": ["cpu_usage", "memory_usage"]
    },
    "slot_extractors": {
      "selector_type": {
        "extractors": [
          {
            "type": "keyword_value",
            "cases": [
              {"terms": ["ip"], "value": "ip"},
              {"terms": ["mac"], "value": "mac"},
              {"terms": ["名称"], "value": "name"}
            ]
          }
        ]
      }
    },
    "llm_slot_extraction": {
      "enabled": false,
      "slots": [],
      "instructions": ""
    },
    "metadata": {}
  }
}`
                }
              }
            ]
          };
        }
      }
    }
  };

  const result = await generateTemplateFromSentence({
    text: "查询近24小时ip为10.1.1.1的交换机cpu利用率最大值",
    currentConfig: {
      matcher: {
        blocked_terms: ["分析", "根因"]
      },
      templates: [
        {
          template_id: "device.cpu.over.list",
          description: "查询CPU利用率超过阈值的设备列表",
          utterances: ["查询最近cpu大于80的设备列表"],
          required_slots: ["query_operator", "cpu_threshold"],
          optional_slots: ["time_range"]
        }
      ]
    },
    apiKey: "test-key",
    client: fakeClient
  });

  assert.equal(result.template.template_id, "network.device.resource.aggregate.by_selector");
  assert.equal(result.analysis.query_operator, "aggregate");
  assert.equal(result.analysis.design_rationale[0], "趋势和聚合值的结果形态不同，因此先拆模板边界。");
});

test("buildGenerationPrompt includes slot completion guidance when current template context is provided", () => {
  const prompt = buildGenerationPrompt({
    text: "查询最近cpu大于80的设备",
    answer: "返回 CPU 超阈值设备列表",
    currentMatch: {
      result: {
        template_id: "device.cpu.over.list",
        status: "partial",
        missing_slots: ["query_operator"]
      }
    },
    currentTemplate: {
      template_id: "device.cpu.over.list",
      query_mode: "metric_query",
      required_slots: ["query_operator", "cpu_threshold"]
    },
    missingSlots: ["query_operator"],
    optimizationMode: "slot_completion",
    currentConfig: {
      templates: []
    }
  });

  assert.match(prompt, /当前优先修复的模板/);
  assert.match(prompt, /当前缺失槽位/);
  assert.match(prompt, /slot_completion/);
  assert.match(prompt, /把 partial 推成 matched/);
});
