import OpenAI from "openai";

import { createBlankTemplate, normalizeTemplate, slugifyTemplateId } from "./utils.js";

const DEFAULT_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1";
const DEFAULT_MODEL = "qwen3-coder-plus";

export const DEFAULT_LLM_SETTINGS = {
  baseUrl: DEFAULT_BASE_URL,
  model: DEFAULT_MODEL
};

export async function generateTemplateFromSentence({
  text,
  currentConfig,
  apiKey,
  baseUrl = DEFAULT_BASE_URL,
  model = DEFAULT_MODEL
}) {
  if (!apiKey) {
    throw new Error("Missing API key.");
  }
  const client = new OpenAI({
    apiKey,
    baseURL: baseUrl
  });
  const response = await client.chat.completions.create({
    model,
    temperature: 0.1,
    response_format: { type: "json_object" },
    messages: [
      {
        role: "system",
        content:
          "You are a senior template designer for a metric-query matcher. " +
          "Only output strict JSON. The system only supports metric_query templates. " +
          "Use only keyword_value and regex extractors."
      },
      {
        role: "user",
        content: buildGenerationPrompt({ text, currentConfig })
      }
    ]
  });
  const content = response.choices?.[0]?.message?.content;
  const payload = typeof content === "string" ? JSON.parse(content) : JSON.parse(content?.[0]?.text || "{}");
  const blank = createBlankTemplate();
  const generatedTemplate = normalizeTemplate({
    ...blank,
    ...(payload.template || {}),
    template_id:
      payload.template?.template_id ||
      inferTemplateId(payload.analysis?.entity, payload.analysis?.metric, payload.analysis?.query_operator, text)
  });
  return {
    analysis: payload.analysis || {},
    template: generatedTemplate
  };
}

export function buildGenerationPrompt({ text, currentConfig }) {
  const sampleTemplates = (currentConfig?.templates || []).slice(0, 10).map((template) => ({
    template_id: template.template_id,
    description: template.description,
    required_slots: template.required_slots,
    optional_slots: template.optional_slots,
    slot_constraints: template.slot_constraints,
    slot_extractors: template.slot_extractors,
    utterances: template.utterances.slice(0, 4)
  }));
  return `
给定一句中文问数 query，帮我把它抽象成一个可直接落到模板系统里的模板 JSON。

要求：
- query_mode 固定写 metric_query
- 真正区分查询形态用 query_operator，例如 count / topn / list
- 模板必须是单意图
- 尽量生成可执行的 slot_extractors
- 只允许 keyword_value 和 regex 两种 extractor
- 如果是阈值、TopN、数值，优先给 regex
- 如果是时间、区域、算子、实体、指标，优先给 keyword_value
- negative_terms 默认包含 原因 / 根因 / 报告 / 总结 / 预测
- llm_slot_extraction 要尽量收窄，只补少量高价值槽位
- 生成的 utterances 至少 5 条，要覆盖语序变化、口语化、typo

当前已有模板样例：
${JSON.stringify(sampleTemplates, null, 2)}

目标句子：
${text}

输出 JSON，结构固定为：
{
  "analysis": {
    "intent": "...",
    "entity": "...",
    "metric": "...",
    "query_operator": "...",
    "required_slots": ["..."],
    "optional_slots": ["..."],
    "notes": ["..."]
  },
  "template": {
    "template_id": "...",
    "query_mode": "metric_query",
    "description": "...",
    "utterances": ["..."],
    "required_slots": ["..."],
    "optional_slots": ["..."],
    "must_terms": [["..."]],
    "negative_terms": ["..."],
    "slot_constraints": {},
    "slot_extractors": {},
    "llm_slot_extraction": {
      "enabled": true,
      "slots": ["..."],
      "instructions": "..."
    },
    "metadata": {}
  }
}
`.trim();
}

function inferTemplateId(entity, metric, queryOperator, text) {
  const raw = [entity, metric, queryOperator, text].filter(Boolean).join(".");
  return slugifyTemplateId(raw, "template.generated");
}
