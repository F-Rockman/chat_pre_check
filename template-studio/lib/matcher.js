import { buildSlotRegistry } from "./extractors.js";
import {
  adaptiveScoreWeights,
  BM25FieldIndex,
  buildUtteranceTermSets,
  constraintScore,
  hasNegativeTerm,
  mixedTerms,
  missingRequiredSlots,
  normalizeCandidateScores,
  reciprocalRankFusion,
  sampleSimilarityFromTerms,
  slotFitScore,
  structuralAlignmentScore,
  weightedScore
} from "./scoring.js";
import { InMemoryVectorIndex, LocalHashVectorProvider, LocalTfidfVectorProvider } from "./vector.js";
import { deepClone, normalizeConfig, normalizeText } from "./utils.js";

export class TemplateMatcher {
  constructor(rawConfig) {
    this.config = normalizeConfig(rawConfig);
    this.settings = this.config.matcher;
    this.templates = Object.fromEntries(this.config.templates.map((template) => [template.template_id, template]));
    this.slotRegistry = buildSlotRegistry(this.config.slot_extractors);
    this.templateSlotRegistries = Object.fromEntries(
      this.config.templates.map((template) => [template.template_id, buildSlotRegistry(this.buildTemplateSlotDefinitions(template))])
    );
    this.templateDocuments = Object.fromEntries(
      this.config.templates.map((template) => [template.template_id, this.buildTemplateDocument(template)])
    );
    this.templateLexicalFields = Object.fromEntries(
      this.config.templates.map((template) => [template.template_id, this.buildTemplateFields(template)])
    );
    this.templateSampleTerms = Object.fromEntries(
      this.config.templates.map((template) => [template.template_id, buildUtteranceTermSets(template.utterances)])
    );
    this.lexicalIndex = new BM25FieldIndex(this.templateLexicalFields, this.settings.lexical_field_weights);
    this.vectorBackend = new InMemoryVectorIndex(buildVectorProvider(this.settings.vector));
    this.vectorBackend.build(this.templateDocuments);
  }

  match(inputText, options = {}) {
    const normText = normalizeText(inputText);
    const sharedSlots = this.slotRegistry.extract(normText);
    const blockedTerm = this.matchBlockedTerm(normText);
    if (blockedTerm) {
      return {
        template_id: -1,
        status: "unmatched",
        score: 0,
        query_mode: null,
        slots: sharedSlots,
        missing_slots: [],
        metadata: {},
        trace: {
          norm_text: normText,
          blocked_term: blockedTerm,
          reason: "blocked_intent"
        }
      };
    }

    const ranked = this.rankTemplates(normText, options.templateIds || null);
    const top = ranked[0];
    const second = ranked[1];
    if (!top || top.score < this.settings.match_threshold || this.isAmbiguous(top, second)) {
      return {
        template_id: -1,
        status: "unmatched",
        score: top?.score || 0,
        query_mode: null,
        slots: sharedSlots,
        missing_slots: [],
        metadata: {},
        trace: {
          norm_text: normText,
          top_candidates: ranked.slice(0, 5),
          threshold: this.settings.match_threshold,
          ambiguity_margin: this.settings.ambiguity_margin
        }
      };
    }

    const template = this.templates[top.template_id];
    const missingSlots = missingRequiredSlots(template, top.slots);
    const status = missingSlots.length ? "partial" : "matched";
    return {
      template_id: template.template_id,
      status,
      score: top.score,
      query_mode: template.query_mode,
      slots: top.slots,
      missing_slots: missingSlots,
      metadata: template.metadata,
      trace: {
        norm_text: normText,
        selected_template: top,
        top_candidates: ranked.slice(0, 5)
      }
    };
  }

  rankTemplates(normText, templateIds = null) {
    const queryTermSet = new Set(mixedTerms(normText));
    const scopeIds = templateIds ? new Set(templateIds) : null;

    const lexicalRecall = filterRanking(this.lexicalIndex.search(normText, this.settings.recall_top_k), scopeIds);
    const vectorRecall = filterRanking(this.vectorBackend.search(normText, this.settings.recall_top_k), scopeIds);
    const sampleRecall = filterRanking(this.sampleRecall(queryTermSet), scopeIds);

    const lexicalScores = normalizeCandidateScores(lexicalRecall);
    const vectorScores = normalizeCandidateScores(vectorRecall);
    const sampleScores = normalizeCandidateScores(sampleRecall);
    const fusionScores = reciprocalRankFusion([lexicalRecall, vectorRecall, sampleRecall], this.settings.fusion_rrf_k);

    const candidateIds = new Set([
      ...Object.keys(lexicalScores),
      ...Object.keys(vectorScores),
      ...Object.keys(sampleScores),
      ...Object.keys(fusionScores)
    ]);
    if (scopeIds) {
      for (const templateId of scopeIds) {
        candidateIds.add(templateId);
      }
    }
    const ranked = [];
    for (const templateId of candidateIds) {
      const template = this.templates[templateId];
      if (!template) {
        continue;
      }
      const slots = this.extractSlots(templateId, normText);
      const weights = adaptiveScoreWeights(this.settings.weights, slots);
      ranked.push(
        this.buildCandidate({
          templateId,
          normText,
          lexicalScore: lexicalScores[templateId] || 0,
          sampleScore: sampleScores[templateId] || 0,
          vectorScore: vectorScores[templateId] || 0,
          fusionScore: fusionScores[templateId] || 0,
          slots,
          weights
        })
      );
    }
    ranked.sort((left, right) => right.score - left.score);
    return ranked;
  }

  sampleRecall(queryTermSet) {
    return Object.entries(this.templateSampleTerms)
      .map(([templateId, utteranceTermSets]) => [
        templateId,
        sampleSimilarityFromTerms(queryTermSet, utteranceTermSets)
      ])
      .sort((left, right) => right[1] - left[1])
      .slice(0, this.settings.recall_top_k);
  }

  extractSlots(templateId, text) {
    return this.templateSlotRegistries[templateId].extract(text);
  }

  buildTemplateSlotDefinitions(template) {
    const relevantSlots = new Set([
      ...(template.required_slots || []),
      ...(template.optional_slots || []),
      ...Object.keys(template.slot_constraints || {}),
      ...Object.keys(template.slot_extractors || {})
    ]);
    const merged = {};
    for (const slotName of relevantSlots) {
      const localDefinition = template.slot_extractors?.[slotName];
      if (localDefinition) {
        merged[slotName] = deepClone(localDefinition);
        continue;
      }
      const sharedDefinition = this.config.slot_extractors?.[slotName];
      if (sharedDefinition) {
        merged[slotName] = deepClone(sharedDefinition);
      }
    }
    return merged;
  }

  buildTemplateDocument(template) {
    const parts = [template.description, ...(template.utterances || [])];
    parts.push(...(template.must_terms || []).map((group) => group.join(" ")));
    return normalizeText(parts.filter(Boolean).join(" "));
  }

  buildTemplateFields(template) {
    const mustTermsText = (template.must_terms || []).map((group) => group.join(" ")).join(" ");
    return {
      description: mixedTerms(normalizeText(template.description)),
      utterances: mixedTerms(normalizeText((template.utterances || []).join(" "))),
      must_terms: mixedTerms(normalizeText(mustTermsText))
    };
  }

  buildCandidate({ templateId, normText, lexicalScore, sampleScore, vectorScore, fusionScore, slots, weights }) {
    const template = this.templates[templateId];
    const slotScore = slotFitScore(template, slots);
    const constraint = constraintScore(template, normText, slots);
    const structure = structuralAlignmentScore(template, slots);
    const total = hasNegativeTerm(template, normText)
      ? 0
      : weightedScore(
          {
            lexical: lexicalScore,
            sample: sampleScore,
            vector: vectorScore,
            fusion: fusionScore,
            slot_fit: slotScore,
            constraint,
            structure
          },
          weights
        );

    return {
      template_id: template.template_id,
      query_mode: template.query_mode,
      score: total,
      lexical_score: lexicalScore,
      sample_score: sampleScore,
      vector_score: vectorScore,
      fusion_score: fusionScore,
      slot_fit_score: slotScore,
      constraint_score: constraint,
      structure_score: structure,
      slots,
      missing_slots: missingRequiredSlots(template, slots),
      metadata: template.metadata,
      trace: {}
    };
  }

  isAmbiguous(top, second) {
    if (!top || !second) {
      return false;
    }
    if (second.score < this.settings.match_threshold) {
      return false;
    }
    return top.score - second.score < this.settings.ambiguity_margin;
  }

  matchBlockedTerm(normText) {
    for (const term of this.settings.blocked_terms || []) {
      if (term && normText.includes(String(term).toLowerCase())) {
        return term;
      }
    }
    return null;
  }
}

function buildVectorProvider(vectorSettings = {}) {
  const provider = String(vectorSettings.provider || "local_tfidf");
  const dimension = Number(vectorSettings.dimension || 512);
  if (provider === "hashing" || provider === "local_hash") {
    return new LocalHashVectorProvider(dimension);
  }
  return new LocalTfidfVectorProvider(dimension);
}

function filterRanking(ranking, scopeIds) {
  if (!scopeIds) {
    return ranking;
  }
  return ranking.filter(([templateId]) => scopeIds.has(templateId));
}
