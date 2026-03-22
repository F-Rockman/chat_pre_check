import { evaluateBatchMatch, summarizeBatchMatches } from "./batch.js";
import { TemplateMatcher } from "./matcher.js";
import { normalizeConfig } from "./utils.js";

const DEFAULT_TARGET_METRIC = "pass_rate";
const DEFAULT_TARGET_VALUE = 0.9;
const DEFAULT_MAX_ROUNDS = 3;
const DEFAULT_MAX_CANDIDATES_PER_ROUND = 5;
const DEFAULT_OPTIMIZATION_STRATEGY = "balanced";

export async function optimizeConfigIteratively({
  items,
  config,
  baseDir,
  targetMetric = DEFAULT_TARGET_METRIC,
  targetValue = DEFAULT_TARGET_VALUE,
  maxRounds = DEFAULT_MAX_ROUNDS,
  maxCandidatesPerRound = DEFAULT_MAX_CANDIDATES_PER_ROUND,
  optimizationStrategy = DEFAULT_OPTIMIZATION_STRATEGY,
  generateCandidate
}) {
  const normalizedItems = Array.isArray(items) ? items.filter((item) => String(item?.text || "").trim()) : [];
  let workingConfig = normalizeConfig(config || {});
  let current = evaluateConfigAgainstItems(workingConfig, normalizedItems, baseDir);
  const initial = summarizeEvaluationState(current, targetMetric);
  const history = [];

  for (let round = 1; round <= maxRounds; round += 1) {
    if (goalReached(current.metrics, targetMetric, targetValue)) {
      break;
    }

    const seeds = selectOptimizationSeeds(current.results, targetMetric, maxCandidatesPerRound, optimizationStrategy);
    if (!seeds.length) {
      history.push({
        round,
        before: summarizeEvaluationState(current, targetMetric),
        after: summarizeEvaluationState(current, targetMetric),
        accepted_count: 0,
        attempted_count: 0,
        stop_reason: "no_candidates",
        actions: []
      });
      break;
    }

    const beforeRound = summarizeEvaluationState(current, targetMetric);
    const actions = [];
    let acceptedCount = 0;

    for (const seed of seeds) {
      const currentTemplate = resolveCurrentTemplate(workingConfig, seed.item, seed.result);
      const generationMode = decideGenerationMode({
        strategy: optimizationStrategy,
        item: seed.item,
        currentResult: seed.result,
        currentTemplate,
        targetMetric
      });
      const proposal = await generateCandidate({
        item: seed.item,
        currentConfig: workingConfig,
        currentResult: seed.result,
        currentEvaluation: seed.evaluation,
        currentTemplate,
        generationMode,
        missingSlots: Array.isArray(seed.result?.missing_slots) ? seed.result.missing_slots : []
      });

      const plan = decideTemplatePlan({
        workingConfig,
        item: seed.item,
        currentResult: seed.result,
        proposalTemplate: proposal.template
      });
      const candidateConfig = applyTemplatePlan(workingConfig, proposal.template, plan);
      const candidateState = evaluateConfigAgainstItems(candidateConfig, normalizedItems, baseDir);
      const improved = isImprovement(candidateState.metrics, current.metrics, targetMetric);

      actions.push({
        item_id: seed.item.id,
        text: seed.item.text,
        answer: seed.item.answer || "",
        previous_template_id: String(seed.result?.template_id ?? ""),
        previous_status: String(seed.result?.status || ""),
        proposal_template_id: proposal.template?.template_id || "",
        strategy: proposal.analysis?.template_strategy || "",
        design_rationale: proposal.analysis?.design_rationale || [],
        generation_mode: generationMode,
        mode: plan.mode,
        target_template_id: plan.targetTemplateId || "",
        accepted: improved,
        before_metric: current.metrics[targetMetric] ?? null,
        after_metric: candidateState.metrics[targetMetric] ?? null
      });

      if (!improved) {
        continue;
      }

      workingConfig = candidateConfig;
      current = candidateState;
      acceptedCount += 1;

      if (goalReached(current.metrics, targetMetric, targetValue)) {
        break;
      }
    }

    history.push({
      round,
      before: beforeRound,
      after: summarizeEvaluationState(current, targetMetric),
      accepted_count: acceptedCount,
      attempted_count: actions.length,
      stop_reason: acceptedCount ? "" : "no_improvement",
      actions
    });

    if (!acceptedCount) {
      break;
    }
  }

  return {
    goal: {
      metric: targetMetric,
      target_value: targetValue,
      strategy: optimizationStrategy
    },
    initial,
    final: summarizeEvaluationState(current, targetMetric),
    optimized_config: workingConfig,
    history,
    reached: goalReached(current.metrics, targetMetric, targetValue)
  };
}

export function evaluateConfigAgainstItems(config, items, baseDir) {
  const normalizedConfig = normalizeConfig(config || {});
  const matcher = new TemplateMatcher(normalizedConfig, { baseDir });
  const results = items.map((item) => {
    const normalizedItem = {
      id: String(item?.id || ""),
      text: String(item?.text || "").trim(),
      expected_template_id: String(item?.expected_template_id || ""),
      expected_status: String(item?.expected_status || ""),
      expected_not_full_match: Boolean(item?.expected_not_full_match),
      answer: String(item?.answer || ""),
      metadata: item?.metadata && typeof item.metadata === "object" ? item.metadata : {}
    };
    const result = matcher.match(normalizedItem.text);
    return {
      item: normalizedItem,
      result,
      evaluation: evaluateBatchMatch(normalizedItem, result)
    };
  });
  const summary = summarizeBatchMatches(results);
  return {
    config: normalizedConfig,
    results,
    summary,
    metrics: computeOptimizationMetrics(summary)
  };
}

export function computeOptimizationMetrics(summary) {
  const total = Number(summary?.total || 0);
  const matched = Number(summary?.status_counts?.matched || 0);
  const partial = Number(summary?.status_counts?.partial || 0);
  const passRate = summary?.pass_rate == null ? null : Number(summary.pass_rate);
  return {
    pass_rate: passRate,
    coverage_rate: total ? (matched + partial) / total : 0,
    matched_rate: total ? matched / total : 0,
    partial_rate: total ? partial / total : 0
  };
}

export function goalReached(metrics, targetMetric, targetValue) {
  const current = metrics?.[targetMetric];
  if (current == null) {
    return false;
  }
  return current >= targetValue;
}

export function isImprovement(candidateMetrics, currentMetrics, targetMetric) {
  const candidatePrimary = metricOrNegativeInfinity(candidateMetrics?.[targetMetric]);
  const currentPrimary = metricOrNegativeInfinity(currentMetrics?.[targetMetric]);
  if (candidatePrimary > currentPrimary + 1e-9) {
    return true;
  }
  if (candidatePrimary < currentPrimary - 1e-9) {
    return false;
  }

  const secondaryKeys = ["matched_rate", "coverage_rate", "pass_rate"];
  for (const key of secondaryKeys) {
    const candidate = metricOrNegativeInfinity(candidateMetrics?.[key]);
    const current = metricOrNegativeInfinity(currentMetrics?.[key]);
    if (candidate > current + 1e-9) {
      return true;
    }
    if (candidate < current - 1e-9) {
      return false;
    }
  }
  return false;
}

export function selectOptimizationSeeds(results, targetMetric, limit, strategy = DEFAULT_OPTIMIZATION_STRATEGY) {
  const ranked = [];
  for (const entry of results) {
    const evaluationFailed = entry.evaluation?.evaluated && !entry.evaluation?.pass;
    const uncovered = entry.result?.status === "unmatched";
    const partial = entry.result?.status === "partial";
    if (!(evaluationFailed || uncovered || partial)) {
      continue;
    }
    ranked.push({
      ...entry,
      priority: scoreSeedPriority(entry, targetMetric, strategy)
    });
  }
  return ranked.sort((left, right) => right.priority - left.priority).slice(0, Math.max(1, limit));
}

export function decideGenerationMode({ strategy = DEFAULT_OPTIMIZATION_STRATEGY, item, currentResult, currentTemplate, targetMetric }) {
  const hasCurrentTemplate = Boolean(currentTemplate);
  const expectsExistingTemplate =
    Boolean(item?.expected_template_id) && hasCurrentTemplate && currentTemplate.template_id === String(item.expected_template_id);
  const isPartial = currentResult?.status === "partial";
  const isUnmatched = currentResult?.status === "unmatched";

  if (strategy === "slot_completion_first") {
    if ((isPartial || expectsExistingTemplate) && hasCurrentTemplate) {
      return "slot_completion";
    }
    return isUnmatched ? "new_template" : "mixed";
  }

  if (strategy === "new_template_first") {
    if (isUnmatched) {
      return "new_template";
    }
    if ((isPartial || expectsExistingTemplate) && hasCurrentTemplate) {
      return "slot_completion";
    }
    return "mixed";
  }

  if ((targetMetric === "matched_rate" || isPartial || expectsExistingTemplate) && hasCurrentTemplate) {
    return "slot_completion";
  }
  if (isUnmatched) {
    return "new_template";
  }
  return "mixed";
}

export function decideTemplatePlan({ workingConfig, item, currentResult, proposalTemplate }) {
  const existingIds = new Set((workingConfig?.templates || []).map((template) => template.template_id));
  const expectedTemplateId = item?.expected_template_id ? String(item.expected_template_id) : "";
  if (expectedTemplateId && existingIds.has(expectedTemplateId)) {
    return {
      mode: "replace_expected",
      targetTemplateId: expectedTemplateId
    };
  }
  if (proposalTemplate?.template_id && existingIds.has(proposalTemplate.template_id)) {
    return {
      mode: "replace_generated",
      targetTemplateId: proposalTemplate.template_id
    };
  }
  if (currentResult?.template_id && existingIds.has(String(currentResult.template_id)) && currentResult.status === "partial") {
    return {
      mode: "replace_predicted_partial",
      targetTemplateId: String(currentResult.template_id)
    };
  }
  return {
    mode: "add",
    targetTemplateId: ""
  };
}

export function applyTemplatePlan(config, proposalTemplate, plan) {
  const next = normalizeConfig(config || {});
  const templates = [...next.templates];
  const candidate = structuredClone(proposalTemplate || {});
  if (plan.mode === "add") {
    candidate.template_id = ensureUniqueTemplateId(templates, candidate.template_id);
    templates.unshift(candidate);
  } else {
    candidate.template_id = plan.targetTemplateId || candidate.template_id;
    const index = templates.findIndex((template) => template.template_id === candidate.template_id);
    if (index >= 0) {
      templates[index] = candidate;
    } else {
      templates.unshift(candidate);
    }
  }
  return normalizeConfig({
    ...next,
    templates
  });
}

function scoreSeedPriority(entry, targetMetric, strategy) {
  let score = 0;
  if (entry.evaluation?.evaluated && !entry.evaluation?.pass) {
    score += 5;
  }
  if (entry.result?.status === "unmatched") {
    score += 4;
  }
  if (entry.result?.status === "partial") {
    score += 2;
  }
  if (targetMetric === "matched_rate") {
    score += entry.result?.status === "partial" ? 1.5 : 0;
  }
  if (strategy === "slot_completion_first" && entry.result?.status === "partial") {
    score += 2;
  }
  if (strategy === "new_template_first" && entry.result?.status === "unmatched") {
    score += 2;
  }
  score += 1 - Number(entry.result?.score || 0);
  return score;
}

function summarizeEvaluationState(state, targetMetric) {
  return {
    summary: state.summary,
    metrics: state.metrics,
    primary_metric: targetMetric,
    primary_value: state.metrics?.[targetMetric] ?? null
  };
}

function ensureUniqueTemplateId(templates, templateId) {
  const existing = new Set(templates.map((template) => template.template_id));
  const baseId = String(templateId || `template.generated.${Date.now()}`);
  let candidate = baseId;
  let counter = 1;
  while (existing.has(candidate)) {
    candidate = `${baseId}.${counter}`;
    counter += 1;
  }
  return candidate;
}

function resolveCurrentTemplate(config, item, result) {
  const templates = Array.isArray(config?.templates) ? config.templates : [];
  const expectedTemplateId = item?.expected_template_id ? String(item.expected_template_id) : "";
  if (expectedTemplateId) {
    const expected = templates.find((template) => template.template_id === expectedTemplateId);
    if (expected) {
      return expected;
    }
  }
  const predictedTemplateId = result?.template_id ? String(result.template_id) : "";
  if (predictedTemplateId) {
    return templates.find((template) => template.template_id === predictedTemplateId) || null;
  }
  return null;
}

function metricOrNegativeInfinity(value) {
  return value == null ? Number.NEGATIVE_INFINITY : Number(value);
}
