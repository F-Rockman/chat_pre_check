import crypto from "node:crypto";

import { mixedTerms } from "./scoring.js";

export class LocalHashVectorProvider {
  constructor(dimension = 512) {
    this.dimension = dimension;
  }

  prepareDocuments() {}

  embedTexts(texts) {
    return texts.map((text) => this.embedOne(text));
  }

  embedOne(text) {
    const vector = Array(this.dimension).fill(0);
    for (const term of mixedTerms(text)) {
      const { bucket, sign } = signedBucket(term, this.dimension);
      vector[bucket] += sign;
    }
    return l2Normalize(vector);
  }
}

export class LocalTfidfVectorProvider {
  constructor(dimension = 512, overflowBucketCount = 128) {
    this.dimension = dimension;
    this.overflowBucketCount = overflowBucketCount;
    this.idfByTerm = {};
    this.vocabulary = {};
    this.overflowOffset = 0;
    this.totalDocs = 1;
    this.defaultIdf = 1;
  }

  prepareDocuments(documents) {
    this.totalDocs = Math.max(1, Object.keys(documents).length);
    const documentTerms = Object.values(documents).map((text) => countTerms(mixedTerms(text)));
    const docFreq = {};
    for (const terms of documentTerms) {
      for (const term of Object.keys(terms)) {
        docFreq[term] = (docFreq[term] || 0) + 1;
      }
    }
    this.idfByTerm = Object.fromEntries(
      Object.entries(docFreq).map(([term, frequency]) => [term, bm25Idf(frequency, this.totalDocs)])
    );
    this.defaultIdf = bm25Idf(0, this.totalDocs);

    const termImportance = {};
    for (const terms of documentTerms) {
      for (const [term, freq] of Object.entries(terms)) {
        const tf = 1 + Math.log(freq);
        const idf = this.idfByTerm[term] ?? this.defaultIdf;
        termImportance[term] = (termImportance[term] || 0) + tf * idf;
      }
    }
    const reservedOverflow = Math.min(Math.max(16, this.overflowBucketCount), Math.max(1, Math.floor(this.dimension / 2)));
    const explicitCapacity = Math.max(1, this.dimension - reservedOverflow);
    const rankedTerms = Object.entries(termImportance).sort((left, right) => {
      if (right[1] !== left[1]) {
        return right[1] - left[1];
      }
      return left[0].localeCompare(right[0]);
    });
    this.vocabulary = Object.fromEntries(
      rankedTerms.slice(0, explicitCapacity).map(([term], index) => [term, index])
    );
    this.overflowOffset = Object.keys(this.vocabulary).length;
  }

  embedTexts(texts) {
    return texts.map((text) => this.embedOne(text));
  }

  embedOne(text) {
    const vector = Array(this.dimension).fill(0);
    const termCounts = countTerms(mixedTerms(text));
    const overflowBuckets = Math.max(0, this.dimension - this.overflowOffset);
    for (const [term, freq] of Object.entries(termCounts)) {
      const weight = (1 + Math.log(freq)) * (this.idfByTerm[term] ?? this.defaultIdf);
      const explicitIndex = this.vocabulary[term];
      if (explicitIndex !== undefined) {
        vector[explicitIndex] += weight;
        continue;
      }
      if (!overflowBuckets) {
        continue;
      }
      const { bucket, sign } = signedBucket(term, overflowBuckets);
      vector[this.overflowOffset + bucket] += sign * weight;
    }
    return l2Normalize(vector);
  }
}

export class InMemoryVectorIndex {
  constructor(provider) {
    this.provider = provider;
    this.vectors = {};
  }

  build(documents) {
    this.provider.prepareDocuments(documents);
    const docIds = Object.keys(documents);
    const embeddings = this.provider.embedTexts(docIds.map((docId) => documents[docId]));
    this.vectors = Object.fromEntries(docIds.map((docId, index) => [docId, embeddings[index]]));
  }

  search(queryText, topK) {
    if (!Object.keys(this.vectors).length) {
      return [];
    }
    const queryVector = this.provider.embedTexts([queryText])[0];
    return Object.entries(this.vectors)
      .map(([docId, vector]) => [docId, cosineSimilarity(queryVector, vector)])
      .sort((left, right) => right[1] - left[1])
      .slice(0, topK);
  }
}

function signedBucket(term, bucketCount) {
  const digest = crypto.createHash("blake2b512").update(term).digest();
  const bucket = digest.readUInt32BE(0) % Math.max(1, bucketCount);
  const sign = digest[4] % 2 === 0 ? 1 : -1;
  return { bucket, sign };
}

function l2Normalize(vector) {
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  if (!norm) {
    return vector;
  }
  return vector.map((value) => value / norm);
}

function cosineSimilarity(left, right) {
  if (!left.length || !right.length) {
    return 0;
  }
  const total = left.reduce((sum, value, index) => sum + value * right[index], 0);
  return Math.max(0, Math.min(1, (total + 1) / 2));
}

function countTerms(terms) {
  return terms.reduce((acc, term) => {
    acc[term] = (acc[term] || 0) + 1;
    return acc;
  }, {});
}

function bm25Idf(docFreq, totalDocs) {
  return Math.log(1 + (totalDocs - docFreq + 0.5) / (docFreq + 0.5));
}
