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

### Scripts
- `scripts/build_vector_indices.py` now reads seed cases from loaded capabilities config (`config.seed_cases`) instead of standalone `seed_cases.json`.
- `scripts/import_seed_cases.py` now imports/merges seed cases into capability blocks.

### Runtime
- Local fallback runtime now consumes `config.seed_cases` from unified capabilities config.

### Docs
- Updated README and guides to reflect unified config model and new import/export paths.

