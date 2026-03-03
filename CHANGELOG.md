# Changelog

## 2026-03-03

### Architecture
- Replaced fragmented business config files with a single source of truth: `configs/capabilities.json`.
- Compiled `capabilities` into runtime structures (`scenes/templates/cases/seed_cases/slot_policies`) in loader, so middleware pipeline stays stable while config complexity drops.
- Removed legacy business config files:
  - `configs/scenes.json`
  - `configs/templates.json`
  - `configs/cases.json`
  - `configs/slot_policies.json`
  - `configs/seed_cases.json`

### AC Prefill
- Upgraded prefill to domain-aware architecture:
  - domain AC manager (`ACDomainPrefillManager`)
  - domain router (`PrefillDomainRouter`)
  - cross-domain conflict arbiter (`PrefillArbiter`)
- Added domain-level policies in `vector.json`:
  - `domain_router`
  - `domain_priority`
  - `slot_domain_priority`
  - `domain_penalty`

### Seed / Template Model
- Consolidated seed cases, recommendations, slot policies, and optional templates under each capability definition.
- Updated seed import script to write back into `capabilities.json` instead of a separate seed file.
- Added unified `capability.intents` model:
  - one intent defines seed-case retrieval fields
  - optional embedded `template` defines executable template fields
  - loader compiles intents into runtime `seed_cases/templates` views

### Scripts
- `scripts/build_vector_indices.py` now reads seed cases from loaded capabilities config (`config.seed_cases`) instead of standalone `seed_cases.json`.
- `scripts/import_seed_cases.py` now imports/merges seed cases into capability blocks.

### Runtime
- Local fallback runtime now consumes `config.seed_cases` from unified capabilities config.
- API route now executes sync engine logic via FastAPI threadpool (`run_in_threadpool`) to avoid event-loop blocking.
- Reordered middleware so `seed_scope_guard` is enforced only before NL2SQL fallback (after template matching).
- Added retriever query-vector LRU cache to reuse embeddings across scene/template/seed retrieval in same query text path.

### Tests
- Added API router thread-model unit test to verify `/v1/precheck/route` uses threadpool execution and preserves `RouteRequest` fields.
- Added config validator unit tests for high-risk guardrails:
  - invalid `query_vector_cache_size`
  - invalid `search_backend`
  - `es` alias acceptance
  - intent semantic minimum fields (`text/label/examples`)
- Added benchmark evaluator unit tests for metric correctness:
  - `missing_slots` subset matching
  - signature stability with slot-order normalization
  - weighted accuracy / exact accuracy / stability / per-type accuracy aggregation
- Added AC multi-domain ranking unit test to verify same-score conflict is ordered by `domain_priority`.

### Docs
- Updated README and guides to reflect unified config model and new import/export paths.
- Unified wording from OpenSearch-only to generic search backend (ES/OS) where applicable.
- Replaced machine-local absolute doc links with repository-relative paths.
- Reorganized docs into two primary Chinese guides:
  - `docs/CAPABILITIES_GUIDE.md` (full field-level design for `capabilities.json`)
  - `docs/DEPLOYMENT_AND_ARCHITECTURE_GUIDE.md` (deployment + backend switch + runtime flow)
- Removed fragmented legacy guides to reduce maintenance complexity.

### Code Readability
- Added Chinese inline comments and docstrings across core modules:
  - engine/pipeline/middlewares/services
  - config loader/validator
  - search backend clients and resolvers
  - benchmark/demo/cli paths
- Standardized comment focus on decision points, fallback paths, ranking logic, and execution order.
