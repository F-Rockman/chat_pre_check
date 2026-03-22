import assert from "node:assert/strict";
import test from "node:test";

import { decideGenerationMode, decideTemplatePlan, optimizeConfigIteratively, selectOptimizationSeeds } from "../lib/optimizer.js";

test("decideTemplatePlan prefers replacing expected template when label exists", () => {
  const plan = decideTemplatePlan({
    workingConfig: {
      templates: [
        {
          template_id: "school.alarm.count"
        }
      ]
    },
    item: {
      expected_template_id: "school.alarm.count"
    },
    currentResult: {
      template_id: -1,
      status: "unmatched"
    },
    proposalTemplate: {
      template_id: "school.alarm.count.candidate"
    }
  });

  assert.equal(plan.mode, "replace_expected");
  assert.equal(plan.targetTemplateId, "school.alarm.count");
});

test("optimizeConfigIteratively keeps accepted proposals until pass_rate target is reached", async () => {
  const items = [
    {
      id: "school-1",
      text: "查询北京第二小学的告警",
      answer: "返回北京第二小学的告警数量",
      expected_template_id: "school.alarm.count",
      expected_status: "matched"
    }
  ];

  const output = await optimizeConfigIteratively({
    items,
    config: {
      matcher: {
        match_threshold: 0.4,
        ambiguity_margin: 0.03,
        recall_top_k: 10
      },
      templates: []
    },
    targetMetric: "pass_rate",
    targetValue: 1,
    maxRounds: 2,
    maxCandidatesPerRound: 2,
    generateCandidate: async ({ item }) => ({
      analysis: {
        intent: item.text,
        template_strategy: "新增一个学校告警模板，先让这批样本有稳定命中。",
        design_rationale: ["当前没有对应模板，因此先新增模板。"]
      },
      template: {
        template_id: "school.alarm.count",
        query_mode: "metric_query",
        description: "查询北京第二小学告警数量",
        utterances: ["查询北京第二小学的告警", "北京第二小学告警数量"],
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
    })
  });

  assert.equal(output.initial.summary.pass_count, 0);
  assert.equal(output.final.summary.pass_count, 1);
  assert.equal(output.reached, true);
  assert.equal(output.history[0].accepted_count, 1);
  assert.equal(output.optimized_config.templates[0].template_id, "school.alarm.count");
});

test("decideGenerationMode prefers slot completion for partial cases under slot_completion_first", () => {
  const mode = decideGenerationMode({
    strategy: "slot_completion_first",
    item: {
      expected_template_id: "device.cpu.over.list"
    },
    currentResult: {
      template_id: "device.cpu.over.list",
      status: "partial"
    },
    currentTemplate: {
      template_id: "device.cpu.over.list"
    },
    targetMetric: "matched_rate"
  });

  assert.equal(mode, "slot_completion");
});

test("selectOptimizationSeeds prioritizes partial samples when slot completion is preferred", () => {
  const seeds = selectOptimizationSeeds(
    [
      {
        item: { id: "u1", text: "未命中样本" },
        result: { status: "unmatched", score: 0.6 },
        evaluation: { evaluated: false, pass: null }
      },
      {
        item: { id: "p1", text: "缺槽位样本" },
        result: { status: "partial", score: 0.5 },
        evaluation: { evaluated: true, pass: false }
      }
    ],
    "matched_rate",
    2,
    "slot_completion_first"
  );

  assert.equal(seeds[0].item.id, "p1");
});
