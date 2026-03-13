import { deepClone, normalizeText } from "./utils.js";

export function buildSlotRegistry(definitions = {}) {
  const registry = {};
  for (const [slotName, definition] of Object.entries(definitions || {})) {
    const slotExtractors = [];
    for (const extractor of definition.extractors || []) {
      const type = String(extractor.type || "").toLowerCase();
      if (type === "keyword_value") {
        slotExtractors.push(new KeywordValueExtractor(extractor.cases || []));
        continue;
      }
      if (type === "regex") {
        slotExtractors.push(new RegexValueExtractor(extractor.patterns || []));
      }
    }
    registry[slotName] = slotExtractors;
  }
  return new SlotExtractorRegistry(registry);
}

class KeywordValueExtractor {
  constructor(cases) {
    this.cases = cases;
  }

  extract(text) {
    for (const entry of this.cases) {
      const terms = (entry.terms || []).map((term) => normalizeText(String(term))).filter(Boolean);
      if (terms.some((term) => text.includes(term))) {
        return deepClone(entry.value);
      }
    }
    return null;
  }
}

class RegexValueExtractor {
  constructor(patterns) {
    this.patterns = patterns
      .filter((entry) => entry && entry.pattern)
      .map((entry) => ({
        regex: new RegExp(String(entry.pattern), "i"),
        group: Number(entry.group ?? 1),
        valueType: String(entry.value_type || "string"),
        min: entry.min ?? null,
        max: entry.max ?? null,
        value: entry.value ?? null
      }));
  }

  extract(text) {
    for (const pattern of this.patterns) {
      const match = pattern.regex.exec(text);
      if (!match) {
        continue;
      }
      if (pattern.value !== null && pattern.value !== undefined) {
        return deepClone(pattern.value);
      }
      const rawValue = match[pattern.group];
      const value = castValue(rawValue, pattern.valueType);
      if (value === null || value === undefined || value === "") {
        continue;
      }
      if (typeof value === "number") {
        if (pattern.min !== null && Number(value) < Number(pattern.min)) {
          continue;
        }
        if (pattern.max !== null && Number(value) > Number(pattern.max)) {
          continue;
        }
      }
      return value;
    }
    return null;
  }
}

class SlotExtractorRegistry {
  constructor(extractors) {
    this.extractors = extractors;
  }

  extract(text) {
    const slots = {};
    for (const [slotName, extractors] of Object.entries(this.extractors)) {
      for (const extractor of extractors) {
        const value = extractor.extract(text);
        if (value !== null && value !== undefined && value !== "") {
          slots[slotName] = value;
          break;
        }
      }
    }
    return slots;
  }
}

function castValue(rawValue, valueType) {
  try {
    if (valueType === "int") {
      return Number.parseInt(rawValue, 10);
    }
    if (valueType === "float") {
      return Number.parseFloat(rawValue);
    }
    return String(rawValue);
  } catch {
    return null;
  }
}
