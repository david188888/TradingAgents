# Research Data Integrity Implementation Plan

**Status:** Archived Plan（历史实施计划，已完成）
**Design:** `docs/archive/designs/2026-08-13-research-data-integrity-design.md`
**Execution order:** A -> B -> C -> D -> E -> F -> UI acceptance
**Deferred:** model switching, model probes, cross-model evaluation, Agent methodology/debate redesign
**Worktree protection:** do not modify the pre-existing uncommitted `research_manager.py`, `DecisionBrief.tsx`, `workbench.css`, or built web assets.

> **Do not use this document as evidence of current implementation behavior.**
> 当前文档入口以 [docs/README.md](../../README.md) 为准；当前事实以代码、测试和 focused current-state docs 为准。

## Delivery rules

1. Write a focused failing regression test before changing behavior.
2. Keep each commit limited to one story or one tightly coupled contract slice.
3. Run focused tests after each task and the broader gate after each story.
4. Do not hide known baseline failures; compare them explicitly.
5. New tests required for this feature must be whitelisted in `.gitignore` and committed.
6. No live provider is an acceptance oracle. Provider behavior tests use deterministic fakes; live access is a separate smoke check.

## Story A1 — Typed capability and attempt contracts

**As a** research-case assembler  
**I want** durable, typed capability and provider-attempt results  
**So that** outage, non-coverage, unsupported capability, invalid payload, staleness, and incomplete coverage cannot collapse into one string.

**Priority:** Must Have  
**Estimate:** 5 points  
**Dependencies:** None

### Files

- Add `tradingagents/dataflows/capability_result.py`.
- Extend `tradingagents/dataflows/coverage.py` only where a compatibility helper is required.
- Add and whitelist `tests/test_capability_result.py`.

### Tasks

- Define frozen Pydantic contracts for `ProviderAttemptV1` and `CapabilityResultV1`.
- Define availability, freshness, attempt-outcome, and stable reason-code literals.
- Implement canonical semantic `capability_result_id` hashing.
- Implement availability/coverage/freshness validation and aggregation.
- Implement the negative-conclusion attempt-set rule and budget-exhaustion behavior.
- Ensure `fetched_at` and `analysis_cutoff_at` optionality follows the approved invariants.

### Acceptance criteria

- `available` requires complete coverage and current/stale freshness.
- Usable unknown coverage is `partial`, never `available`.
- Non-payload results require unavailable coverage and unknown freshness.
- `not_covered` is impossible with an unobserved required source.
- Budget exhaustion produces `provider_unavailable` with durable skipped attempts.
- Cutoff-resolution failure emits `invalid`, no fetch timestamp, and no provider-reaching attempt.
- Canonical hashing is stable and excludes its own ID and publication-envelope fields.

## Story A2 — Identity preflight and frozen cutoff

**As a** historical research run  
**I want** a verified, frozen market-time cutoff  
**So that** later data cannot leak into an as-of analysis.

**Priority:** Must Have  
**Estimate:** 5 points  
**Dependencies:** A1

### Files

- Add `tradingagents/research/analysis_cutoff.py`.
- Extend `tradingagents/research/horizon_policy.py` with a versioned cutoff-resolution policy.
- Extend the existing identity/market validation prefetch path under `tradingagents/agents/utils/market_data_validation_tools.py`.
- Extend `tradingagents/agents/utils/agent_states.py` and `tradingagents/graph/propagation.py` for the frozen cutoff/result state.
- Add and whitelist `tests/test_analysis_cutoff.py`.

### Tasks

- Resolve A-share cutoff as end-of-day Asia/Shanghai.
- Resolve global cutoff from verified primary-exchange identity and market timezone.
- Freeze the cutoff before time-sensitive fetch/filter nodes.
- Stop time-sensitive fetches when cutoff resolution fails.
- Normalize comparisons to UTC.
- Preserve the identity reference used for resolution.

### Acceptance criteria

- A-share and known global exchanges yield deterministic UTC cutoffs.
- Unknown global exchange timezone yields typed invalid status and invokes no time-sensitive provider.
- Publication/event timestamps after the cutoff are rejected or filtered according to whether they were selected already.
- `fetched_at`/`committed_at` after cutoff does not alone imply leakage when a preserved point-in-time observation proves availability.

## Story B1 — Core routing and time-series correctness

**As a** company researcher  
**I want** financial statements and price history to preserve actual provider and time semantics  
**So that** global research works and historical rows are not fabricated.

**Priority:** Must Have  
**Estimate:** 5 points  
**Dependencies:** A1

### Files

- Modify `tradingagents/default_config.py`.
- Modify `tradingagents/dataflows/interface.py` only for typed attempt adaptation and correct default reachability.
- Modify `tradingagents/dataflows/stockstats_utils.py`.
- Add and whitelist `tests/test_core_data_integrity.py`.

### Tasks

- Add yfinance/Alpha Vantage to default global statement fallback chains.
- Verify explicit vendor selection remains strict.
- Remove OHLCV backward fill; drop or mark unusable rows without fabricating volume.
- Make A-share current-day cache obey a shared freshness/TTL policy.
- Preserve fallback source and attempt outcomes.

### Acceptance criteria

- All three global statement methods reach a global provider under default configuration.
- A future row never fills an earlier missing OHLCV value.
- Historical cache remains reusable; stale current-day cache refreshes.
- Provider cooldown is never converted to `NoMarketDataError` or `not_covered`.

## Story B2 — Identity and news-time correctness

**As a** company researcher  
**I want** ticker identity and news windows validated deterministically  
**So that** facts cannot be attached to the wrong company or wrong date.

**Priority:** Must Have  
**Estimate:** 3 points  
**Dependencies:** A1, A2

### Files

- Modify `tradingagents/dataflows/ticker_utils.py`.
- Modify `tradingagents/dataflows/company_resolution.py` if required for ambiguity handling.
- Modify `tradingagents/dataflows/news_curator.py`.
- Add and whitelist `tests/test_identity_and_news_time.py`.

### Tasks

- Route explicit A-share suffixes through strict market/code validation.
- Reject suffix/code conflicts.
- Normalize news timestamps to timezone-aware UTC.
- Exclude unknown publication dates from recency and coverage while retaining displayable limited items.
- Test market-date boundary conversions.

### Acceptance criteria

- `600519.SZ` and equivalent conflicts are rejected.
- Unknown-date news cannot satisfy company-event coverage.
- Offset timestamps on opposite sides of a market-date boundary classify deterministically.

## Story C — Frozen fundamentals prefetch bundle

**As a** Fundamentals Analyst  
**I want** one horizon-bounded, durable statement snapshot  
**So that** the report and eligibility use the same company data without unconstrained second fetches.

**Priority:** Must Have  
**Estimate:** 8 points  
**Dependencies:** A1, A2, B1

### Files

- Add `tradingagents/research/fundamentals_prefetch.py`.
- Add `tradingagents/agents/utils/fundamentals_data_tools.py`.
- Extend `tradingagents/agents/utils/agent_states.py` and `tradingagents/graph/propagation.py`.
- Extend `tradingagents/graph/setup.py` with a prefetch node before Fundamentals Analyst.
- Extend `tradingagents/execution/output_publisher.py` and `tradingagents/research/evidence_registry.py` with the new state key.
- Adapt `tradingagents/agents/analysts/fundamentals_analyst.py` only if necessary to consume the frozen bundle; do not redesign its methodology.
- Add and whitelist `tests/test_fundamentals_prefetch.py`.

### Tasks

- Translate horizon policy windows into bounded quarterly/annual statement requests.
- Preserve fiscal period, filing/publication timestamp, units, currency, source, attempts, and limitations.
- Build a canonical JSON bundle and typed capability results for quarterly and annual fundamentals.
- Reuse the current-run bundle/request cache for later Analyst tool calls.
- Persist the bundle as a durable evidence artifact.

### Acceptance criteria

- Short/medium/long request exactly the approved windows.
- Historical fixtures exclude post-cutoff restatements and unknown filing dates from required coverage.
- Analyst access does not trigger a duplicate unconstrained fetch.
- Bundle replay yields the same semantic result IDs.

## Story D — Official-disclosure capability closure

**As a** medium/long company researcher  
**I want** official-disclosure availability represented honestly  
**So that** A-share evidence is credited and missing global SEC support is not disguised.

**Priority:** Must Have  
**Estimate:** 5 points  
**Dependencies:** A1, A2, C

### Files

- Modify `tradingagents/agents/utils/news_data_tools.py`.
- Extend `tradingagents/research/evidence_registry.py`.
- Extend `tradingagents/execution/output_publisher.py` capability extraction.
- Add and whitelist `tests/test_official_disclosure_capability.py`.

### Tasks

- Register exchange/CNINFO A-share announcement evidence as `official_disclosures`.
- Persist negative and skipped attempt results, not only successful supplement rows.
- Emit global `not_supported` with `official_filings_provider_not_implemented`.
- Preserve publication time and source identity.

### Acceptance criteria

- A-share official coverage can become complete from accepted official sources.
- Global medium/long always expose the explicit unsupported result in this release.
- Unsupported is distinguishable from outage and symbol non-coverage in durable replay.

## Story E1 — Registry selection and fatal integrity

**As a** ResearchCase assembler  
**I want** deterministic artifact selection and typed fatal errors  
**So that** retries replay consistently and corrupted/future/cross-run evidence never degrades silently.

**Priority:** Must Have  
**Estimate:** 8 points  
**Dependencies:** C, D

### Files

- Modify `tradingagents/execution/output_publisher.py`.
- Modify `tradingagents/research/evidence_registry.py`.
- Modify `tradingagents/execution/runner.py` only outside the user-modified Research Manager file.
- Add typed integrity errors under `tradingagents/research/` or reuse an existing narrow error module.
- Add and whitelist `tests/test_evidence_registry_integrity.py`.

### Tasks

- Put artifact ID, committed/event sequence, run ID, captured/committed timestamps in the publication envelope.
- Enforce at most one capability result per capability/committed sequence.
- Select greatest eligible `(committed_sequence, event_sequence, artifact_id)`.
- Persist selected semantic/artifact/coverage IDs into publication input.
- Separate recoverable absence from corruption, linkage, identity, and selected post-cutoff violations.
- Emit safe `FAIL_STOP` shell with substantive claims withheld.

### Acceptance criteria

- A later committed retry wins deterministically and Reader replay does not reselect.
- Corrupt hash, cross-run link, wrong identity, or selected post-cutoff evidence cannot publish a partial substantive case.
- Safely filterable post-cutoff candidate rows degrade coverage without fatal failure.

## Story E2 — Eligibility, stance, and missing-capability actions

**As a** learning-oriented Reader user  
**I want** missing core evidence to limit conclusions without hiding useful verified facts  
**So that** I can learn from the available evidence without mistaking an incomplete report for a supported thesis.

**Priority:** Must Have  
**Estimate:** 5 points  
**Dependencies:** E1

### Files

- Modify `tradingagents/research/eligibility.py`.
- Modify `tradingagents/research/case_assembly.py` without changing the user-modified `research_manager.py`.
- Add additive legacy-safe validation/defaults in `tradingagents/agents/schemas/_research_case.py` only if required.
- Add and whitelist `tests/test_research_eligibility_closure.py`.

### Tasks

- Make eligibility consume typed capability status plus coverage.
- Return forced rating and deterministic missing-capability actions.
- Override incompatible model rating after draft parsing.
- Create/merge code-owned unknown and review actions from a versioned mapping.
- Validate unavailable required capability cannot coexist with a non-insufficient rating.
- Add pre-change serialized Reader golden.

### Acceptance criteria

- Required unavailable still publishes verified local claims but forces `insufficient_evidence`.
- Required stale/partial caps eligibility at `limited`.
- Optional failure does not force the top-level rating.
- Legacy ResearchCaseV2 artifact still opens.
- Global medium/long fixture is limited/insufficient because SEC is intentionally unsupported.

## Story F — Policy matrix, audit projection, documentation, and regression

**As a** maintainer  
**I want** the new data semantics enforced by CI and visible in audit surfaces  
**So that** later changes cannot silently reintroduce ambiguous states.

**Priority:** Must Have  
**Estimate:** 5 points  
**Dependencies:** A–E

### Files

- Add and whitelist `tests/test_research_policy_matrix.py`.
- Extend `tradingagents/observability/provenance.py` and relevant audit projection only with already-recorded safe fields.
- Update the legacy `docs/archive/legacy/learning-research-reader-2026-08-13.md` (historical record) and `docs/a-share-data-capabilities.md` as the implementation evolved.
- Modify `.gitignore` to track all new integrity tests.

### Tasks

- Add six-cell horizon/market closure matrix.
- Encode per-cell expectations, including global medium/long unsupported SEC behavior.
- Expose safe availability, freshness, period, provider, fallback, and reason codes.
- Run full backend/frontend gates and classify baseline failures.

### Acceptance criteria

- A-share all horizons and global short can reach full with complete fixtures.
- Global medium/long remain limited/insufficient in this release.
- Fatal fixtures produce safe shells; unavailable fixtures produce limited reports.
- No new unrelated test failures.
- Documentation matches implemented state transitions.

## UI acceptance — Browser and Computer Use

**Priority:** Must Have  
**Estimate:** 3 points  
**Dependencies:** F

### Tasks

- Start the production local application path.
- Use a deterministic acceptance fixture that injects a named required-provider outage/cooldown.
- Use the in-app Browser for run creation, progress inspection, Reader replay, Audit Center, console, and request checks.
- Run a separate credentialed live smoke test only if credentials are already available.
- Use Computer Use for macOS rendering, clipping, scroll, refresh/back/re-entry checks.

### Acceptance criteria

- The injected outage is not described as company non-coverage.
- The run completes with `insufficient_evidence`, missing reason, next action, and retained verified facts.
- Refresh/reopen produces the same Reader state.
- No sensitive debug payload appears in the initial DOM.
- Desktop layout remains usable without modifying the existing uncommitted Reader/CSS work.

## Definition of Done

- Every story acceptance criterion is met.
- Focused and matrix tests are tracked and green.
- Full regression shows no new unrelated failures versus baseline.
- Ruff, frontend typecheck, and relevant frontend tests pass.
- Browser and desktop acceptance pass.
- The implementation and docs agree.
