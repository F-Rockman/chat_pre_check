const QUERY_KEYS = ["text", "query", "question", "input", "utterance", "prompt"];
const ANSWER_KEYS = ["answer", "response", "output"];
const EXPECTED_TEMPLATE_KEYS = ["expected_template_id", "expectedTemplateId", "template_id", "templateId"];
const EXPECTED_STATUS_KEYS = ["expected_status", "expectedStatus", "status"];
const EVALUATION_BUCKETS = ["matched", "partial", "unmatched", "not_full_match"];
const CONTAINER_KEYS = ["items", "queries", "cases", "data", "records"];

export function parseBatchSource(content, filename = "") {
  const raw = String(content || "");
  const trimmed = raw.trim();
  if (!trimmed) {
    return {
      format: "empty",
      source_name: filename || "",
      items: [],
      warnings: ["输入内容为空。"]
    };
  }

  const extension = getExtension(filename);
  if (extension === ".json") {
    return parseJsonSource(trimmed, filename);
  }
  if (extension === ".jsonl" || extension === ".ndjson") {
    return parseJsonLinesSource(trimmed, filename);
  }

  const jsonResult = parseJsonSource(trimmed, filename, { tolerateFailure: true });
  if (jsonResult) {
    return jsonResult;
  }

  const jsonLinesResult = parseJsonLinesSource(trimmed, filename, { tolerateFailure: true });
  if (jsonLinesResult) {
    return jsonLinesResult;
  }

  return parsePlainTextSource(trimmed, filename);
}

export function summarizeBatchMatches(results) {
  const statusCounts = {
    matched: 0,
    partial: 0,
    unmatched: 0
  };
  let evaluatedCount = 0;
  let passCount = 0;
  let failCount = 0;

  for (const entry of results) {
    const status = String(entry?.result?.status || "unmatched");
    statusCounts[status] = (statusCounts[status] || 0) + 1;
    if (entry?.evaluation?.evaluated) {
      evaluatedCount += 1;
      if (entry.evaluation.pass) {
        passCount += 1;
      } else {
        failCount += 1;
      }
    }
  }

  return {
    total: results.length,
    status_counts: statusCounts,
    evaluated_count: evaluatedCount,
    pass_count: passCount,
    fail_count: failCount,
    pass_rate: evaluatedCount ? passCount / evaluatedCount : null
  };
}

export function evaluateBatchMatch(item, result) {
  const expectedTemplateId = item?.expected_template_id ? String(item.expected_template_id) : "";
  const expectedStatus = item?.expected_status ? String(item.expected_status) : "";
  const checks = [];

  if (expectedTemplateId) {
    checks.push({
      field: "template_id",
      expected: expectedTemplateId,
      actual: String(result?.template_id ?? ""),
      pass: String(result?.template_id ?? "") === expectedTemplateId
    });
  }

  if (expectedStatus) {
    checks.push({
      field: "status",
      expected: expectedStatus,
      actual: String(result?.status ?? ""),
      pass: String(result?.status ?? "") === expectedStatus
    });
  }

  if (item?.expected_not_full_match) {
    checks.push({
      field: "not_full_match",
      expected: "status != matched",
      actual: String(result?.status ?? ""),
      pass: String(result?.status ?? "") !== "matched"
    });
  }

  if (!checks.length) {
    return {
      evaluated: false,
      pass: null,
      message: "未提供期望结果，已返回观测值。"
    };
  }

  const failed = checks.find((check) => !check.pass);
  return {
    evaluated: true,
    pass: !failed,
    checks,
    message: failed
      ? `${failed.field} 期望 ${failed.expected}，实际 ${failed.actual || "(空)"}`
      : "与期望结果一致。"
  };
}

export async function batchGenerateTemplates(items, generateOne) {
  const results = [];
  let successCount = 0;
  let failureCount = 0;

  for (const item of items) {
    try {
      const output = await generateOne(item);
      successCount += 1;
      results.push({
        item,
        ok: true,
        output
      });
    } catch (error) {
      failureCount += 1;
      results.push({
        item,
        ok: false,
        error: error instanceof Error ? error.message : String(error)
      });
    }
  }

  return {
    total: items.length,
    success_count: successCount,
    failure_count: failureCount,
    results
  };
}

function parseJsonSource(trimmed, filename, options = {}) {
  try {
    const payload = JSON.parse(trimmed);
    const normalized = normalizeStructuredPayload(payload);
    return {
      format: normalized.format,
      source_name: filename || "",
      items: normalized.items,
      warnings: normalized.warnings
    };
  } catch (error) {
    if (options.tolerateFailure) {
      return null;
    }
    throw new Error(`JSON 解析失败：${error.message}`);
  }
}

function parseJsonLinesSource(trimmed, filename, options = {}) {
  const lines = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return {
      format: "jsonl",
      source_name: filename || "",
      items: [],
      warnings: ["JSONL 输入为空。"]
    };
  }

  const items = [];
  const warnings = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    try {
      const parsed = JSON.parse(line);
      const item = normalizeBatchRecord(parsed, items.length);
      if (item) {
        items.push(item);
      } else {
        warnings.push(`第 ${index + 1} 行没有解析出有效 query。`);
      }
    } catch (error) {
      if (options.tolerateFailure) {
        return null;
      }
      throw new Error(`第 ${index + 1} 行 JSONL 解析失败：${error.message}`);
    }
  }

  return {
    format: "jsonl",
    source_name: filename || "",
    items,
    warnings
  };
}

function parsePlainTextSource(trimmed, filename) {
  const items = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line, index) => normalizeBatchRecord(line, index))
    .filter(Boolean);

  return {
    format: "text",
    source_name: filename || "",
    items,
    warnings: []
  };
}

function normalizeStructuredPayload(payload) {
  if (Array.isArray(payload)) {
    return {
      format: "json_array",
      items: payload.map((item, index) => normalizeBatchRecord(item, index)).filter(Boolean),
      warnings: []
    };
  }

  if (payload && typeof payload === "object") {
    const bucketKeys = Object.keys(payload).filter((key) => EVALUATION_BUCKETS.includes(key));
    if (bucketKeys.length) {
      const items = [];
      for (const bucket of bucketKeys) {
        const records = Array.isArray(payload[bucket]) ? payload[bucket] : [];
        for (const record of records) {
          const normalized = normalizeBatchRecord(record, items.length, {
            expectedStatus: bucket === "not_full_match" ? "" : bucket
          });
          if (normalized) {
            if (bucket === "not_full_match") {
              normalized.expected_not_full_match = true;
            }
            items.push(normalized);
          }
        }
      }
      return {
        format: "evaluation_cases",
        items,
        warnings: []
      };
    }

    for (const key of CONTAINER_KEYS) {
      if (Array.isArray(payload[key])) {
        return {
          format: key,
          items: payload[key].map((item, index) => normalizeBatchRecord(item, index)).filter(Boolean),
          warnings: []
        };
      }
    }

    const single = normalizeBatchRecord(payload, 0);
    if (single) {
      return {
        format: "single_json",
        items: [single],
        warnings: []
      };
    }
  }

  throw new Error("当前文件格式不支持批量导入，请使用 txt / json / jsonl。");
}

function normalizeBatchRecord(record, index, options = {}) {
  if (typeof record === "string") {
    const text = record.trim();
    if (!text) {
      return null;
    }
    return {
      id: `row-${index + 1}`,
      text,
      expected_template_id: "",
      expected_status: options.expectedStatus || "",
      answer: "",
      metadata: {}
    };
  }

  if (!record || typeof record !== "object") {
    return null;
  }

  const text = firstNonEmptyString(record, QUERY_KEYS);
  if (!text) {
    return null;
  }

  const metadata = { ...record };
  for (const key of [
    ...QUERY_KEYS,
    ...ANSWER_KEYS,
    ...EXPECTED_TEMPLATE_KEYS,
    ...EXPECTED_STATUS_KEYS,
    "id"
  ]) {
    delete metadata[key];
  }

  return {
    id: String(record.id || `row-${index + 1}`),
    text,
    answer: firstNonEmptyString(record, ANSWER_KEYS),
    expected_template_id: firstNonEmptyString(record, EXPECTED_TEMPLATE_KEYS),
    expected_status: String(options.expectedStatus || firstNonEmptyString(record, EXPECTED_STATUS_KEYS) || ""),
    metadata
  };
}

function firstNonEmptyString(record, keys) {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function getExtension(filename) {
  const name = String(filename || "").toLowerCase();
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index) : "";
}
