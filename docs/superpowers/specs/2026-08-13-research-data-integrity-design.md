# Research Data Integrity and Eligibility Closure

**Status:** Approved design, pending written-spec review  
**Date:** 2026-08-13  
**Scope:** First implementation subproject for the learning-oriented TradingAgents roadmap  
**Out of scope:** Cross-model portability, model capability probing, cross-model golden evaluation, Agent methodology redesign, debate redesign, ResearchMemory, and Reader layout redesign

## 1. Purpose

TradingAgents is a learning-oriented company research system, not a trading or execution engine. The first implementation subproject must make its data semantics trustworthy before changing Agent behavior.

The system must distinguish:

- a provider successfully returning usable data;
- incomplete or stale data;
- a healthy provider explicitly not covering a symbol;
- a capability that the application has not implemented;
- a provider that could not be observed because of outage, authentication, throttling, timeout, or cooldown;
- a payload that was observed but cannot be trusted.

When a required capability is unavailable, the system must still publish a useful limited research report. The top-level stance must be forced to `insufficient_evidence`, while verified local facts, inferences, unknowns, limitations, and next validation actions remain visible.

## 2. First-principles constraints

1. Data truth is code-owned. An LLM may interpret evidence, but it must not decide whether data existed, was current, covered the requested period, or belonged to the requested symbol.
2. Missing data is not zero and provider failure is not no coverage.
3. A rendered Markdown or sentinel string is not a state contract.
4. Historical research must not consume facts observed after its analysis date.
5. A result that is incomplete but useful should degrade transparently rather than disappear.
6. Data that cannot be attributed safely to the requested instrument must stop publication.
7. The change must evolve the existing provider, bundle, coverage, artifact, Evidence Registry, eligibility, and Reader path rather than introduce a parallel research platform.

## 3. Product decisions

The following decisions were explicitly approved:

- Missing official disclosures or core fundamentals does not abort the whole run.
- Any unavailable core required capability forces the top-level research stance to `insufficient_evidence`.
- Local claims may still be published as `fact`, `inference`, or `unknown` when their own evidence requirements are satisfied.
- The implementation uses an evolutionary contract layer, not localized string patches and not a full data-platform rewrite.
- `not_supported` is distinct from provider unavailability and symbol non-coverage.

## 4. Target architecture

```text
Horizon Policy
  -> deterministic provider attempts
  -> typed capability result
  -> durable evidence bundle
  -> Evidence Registry coverage
  -> AnalysisContext summary
  -> Analyst consumption
  -> deterministic eligibility and top-level stance cap
  -> ResearchCaseV2 / Reader
```

Existing providers, `BundleCoverageV1`, durable artifacts, `ResearchCaseV2`, and Reader remain the primary architecture.

## 5. Contracts

### 5.1 CapabilityResultV1

`CapabilityResultV1` is bundle-level metadata. The payload stays in the existing evidence bundle; this contract describes whether and how the capability was observed.

```text
CapabilityResultV1
  schema_version
  capability
  symbol
  market
  analysis_date
  availability
  freshness
  coverage
  source_ids[]
  artifact_id?
  fallback_from[]
  degradation_codes[]
  limitations[]
```

Availability is one of:

- `available`
- `partial`
- `not_covered`
- `not_supported`
- `provider_unavailable`
- `invalid`

Freshness is a separate dimension:

- `current`
- `stale`
- `unknown`

Coverage remains represented by the existing `BundleCoverageV1` and its `complete | partial | unknown | unavailable` completeness contract. Separating availability, freshness, and coverage prevents impossible single-enum compromises such as losing the fact that a dataset is both complete for its requested historical window and stale relative to the current run.

### 5.2 VendorAttemptOutcome

Provider routing uses an internal attempt outcome instead of a public sentinel string:

- `observed`
- `not_covered`
- `provider_failed`
- `not_supported`
- `invalid_payload`
- `skipped_unobserved`

Each outcome retains the provider, source identity, attempt/call identity, error category, timestamps, and artifact/provenance linkage when present.

Legacy text-returning tools may render these outcomes at their boundary. Core routing, bundle construction, Registry, and eligibility must consume typed state.

## 6. Deterministic aggregation rules

1. A required source or source group that returns schema-valid data and satisfies its requested coverage produces `available`.
2. Usable data with incomplete coverage produces `partial`.
3. `not_covered` is allowed only when all eligible observations required to make that claim were actually attempted and returned authoritative non-coverage.
4. Any required provider that remains unobserved because of outage, authentication, rate limiting, timeout, or cooldown prevents a `not_covered` conclusion and produces `provider_unavailable` unless another accepted source group independently satisfies the capability.
5. A capability without an implemented producer produces `not_supported` with a stable reason code.
6. A payload that violates schema, identity, period, or integrity requirements produces `invalid`.
7. When an accepted fallback independently satisfies the full source requirement, the capability may be `available`; the failed primary remains visible through `fallback_from` and provenance.
8. Optional source failure does not lower a fully satisfied required source group.

## 7. Cache and historical-date semantics

When a live source is unavailable but a compatible last-good artifact exists:

- the result may remain `available` or `partial`;
- freshness becomes `stale`;
- actual source and `fetched_at` remain visible;
- decision eligibility is capped at `limited` for a stale required capability;
- the cache must be compatible with the requested symbol, market, capability, period, price basis, and analysis-date boundary.

A historical run must not use a fact published or observed after its analysis date. A later cache write may be used only when the underlying source observation itself is demonstrably at or before the historical analysis date and the artifact preserves that distinction.

## 8. Core data corrections

The subproject includes the following independent correctness fixes:

1. Global balance sheet, cash-flow, and income-statement default routing must reach yfinance and Alpha Vantage instead of stopping at A-share-only providers.
2. OHLCV cleaning must not backward-fill historical rows with future prices or volume. Unusable rows are dropped or explicitly marked missing.
3. Explicit A-share market suffixes must use strict code/market validation.
4. A-share current-day cache follows the same freshness policy as the global path.
5. News timestamps are normalized to timezone-aware UTC before market-date filtering.
6. News with unknown publication time may be displayed with a limitation but cannot satisfy time-window coverage or recency requirements.

## 9. Deterministic prefetch and capability closure

### 9.1 Fundamentals

Add `fundamentals_prefetch_bundle` before the Fundamentals Analyst.

- Short: quarterly fundamentals are optional.
- Medium: eight quarters are required; five annual years are optional.
- Long: five annual years are required; twelve quarters are optional.

The bundle records statement type, fiscal period, publication/filing date when available, requested and observed windows, source, units, currency, and limitations.

The bundle is the canonical current-run snapshot. A later Analyst tool request must reuse the current run's frozen data or request cache rather than silently perform an unconstrained second fetch.

### 9.2 Official disclosures

- A-share research reuses exchange/CNINFO announcement evidence and registers `official_disclosures` coverage.
- Global SEC support is not implemented as part of this subproject. Global official disclosure coverage therefore produces `not_supported` with `official_filings_provider_not_implemented`.
- Global medium and long research still completes, but its top-level stance is deterministically `insufficient_evidence` until a later SEC integration subproject supplies this capability.

### 9.3 Closure invariant

Every required capability in the horizon policy must have:

```text
policy declaration
  -> producer
  -> durable artifact
  -> Evidence Registry coverage
  -> eligibility consumer
```

The invariant is tested for all three horizons and both supported market kinds.

## 10. Eligibility and publication

The existing report remains publishable when data is missing.

- All required capabilities complete/current and the Evidence Gate permits publication: eligibility may be `full`.
- A required capability that is partial or stale: eligibility is at most `limited`.
- A required capability that is `not_covered`, `not_supported`, `provider_unavailable`, or `invalid`: the report remains publishable, but the top-level stance is forced to `insufficient_evidence`.
- Optional capability failure affects only related limitations and claim confidence.
- A model-provided stance or confidence cannot upgrade deterministic eligibility.

Existing verified claims remain visible. The missing capability must yield an `unknown` with a stable reason and a next validation action.

`FAIL_STOP` is reserved for cases where safe attribution or temporal integrity is impossible, including:

- instrument identity conflict;
- evidence observed after the analysis-date boundary;
- corrupted artifact/hash or cross-run evidence linkage;
- payload identity that cannot be associated safely with the requested instrument.

## 11. Compatibility and migration

- Public Reader schema major is unchanged.
- Existing completed runs and durable Reader artifacts are not rewritten.
- Existing state bundle keys continue to carry canonical JSON strings.
- `CoveredText` and legacy text-returning tools remain available at compatibility boundaries.
- New typed metadata is added within versioned bundles and is rendered to text only at legacy boundaries.
- The implementation does not change Analyst count, debate order, prompts, model/provider selection, or Reader layout.
- Python and semantic data-contract changes must invalidate incompatible checkpoints through the existing fingerprint mechanism. Methodology-asset fingerprinting belongs to a later subproject.

The current uncommitted changes to `research_manager.py`, `DecisionBrief.tsx`, workbench CSS, and built web assets are outside this subproject and must not be overwritten or folded into its commits.

## 12. Implementation increments

### Increment A: contract and state-transition tests

- Introduce typed capability and provider-attempt contracts.
- Add deterministic aggregation functions.
- Add unit tests for every valid and invalid transition.

### Increment B: independent data correctness fixes

- Correct global statement routing.
- Remove future OHLCV backward fill.
- Enforce strict ticker validation.
- Unify current-day cache freshness.
- Correct news timezone and unknown-date behavior.

Each correction starts with a focused failing regression test.

### Increment C: fundamentals prefetch

- Add the deterministic bundle builder and graph prefetch node.
- Persist the bundle as an evidence artifact.
- Make Analyst access reuse the frozen current-run result.

### Increment D: official disclosure coverage

- Register existing A-share official evidence.
- Emit explicit `not_supported` global coverage until SEC integration exists.

### Increment E: Registry and eligibility closure

- Register every required capability.
- Add closure tests.
- Enforce the top-level `insufficient_evidence` cap.

### Increment F: provenance and documentation

- Record availability, freshness, period, unit, currency, actual provider, and fallback.
- Update the learning research and data-capability documentation.

## 13. Test strategy

### 13.1 Unit tests

- Provider attempt to capability result transitions.
- No-data versus unobserved-provider distinctions.
- Fallback source preservation.
- Stale-cache and historical-date rules.
- Contract validation and stable reason codes.

### 13.2 Provider routing tests

Use deterministic fake providers for:

- primary failure plus fallback success;
- non-coverage plus an unobserved provider;
- non-coverage plus provider outage;
- cooldown and recovery;
- global statement route reachability;
- wrong symbol/market suffix;
- payload identity mismatch.

### 13.3 Time integrity tests

- No future backward fill in OHLCV.
- Current-day A-share cache TTL.
- Historical as-of isolation.
- Timezone boundary cases.
- Unknown-date news excluded from coverage.
- Fiscal period, filing date, and analysis date remain distinct.

### 13.4 Policy closure matrix

Parameterize:

```text
short | medium | long
x
a_share | global
```

Test a complete fixture, a partial/stale fixture, a required-unavailable fixture, and an identity-conflict fixture.

Expected results:

- complete -> `full` is reachable;
- partial/stale -> at most `limited`;
- required unavailable -> run completes and stance is `insufficient_evidence`;
- identity conflict -> `FAIL_STOP`.

### 13.5 Regression checks

After each increment run:

- focused unit tests;
- relevant dataflow/research/graph integration tests;
- tracked Reader contract tests;
- full pytest compared with the recorded pre-change baseline;
- Ruff;
- frontend typecheck and existing tests.

The pre-change workspace has known failures. Completion requires no new failures, all subproject tests passing, and related old failures fixed where the changed behavior supersedes them. Network-, credential-, and sandbox-dependent failures must be reported separately rather than hidden.

## 14. Browser and desktop acceptance

Use the user-requested in-app browser as the primary UI interaction surface. Validate:

1. Create an A-share medium company research run.
2. Inspect data progress and provider failure identity.
3. Open the completed Reader.
4. Verify `insufficient_evidence`, missing reasons, and next validation actions.
5. Verify supported local facts remain readable.
6. Refresh and reopen the run to verify durable replay.
7. Inspect Audit Center to ensure outage/cooldown is not rendered as company non-coverage.
8. Check browser console, failed requests, and initial DOM for regressions or sensitive debug leakage.

If real credentials are unavailable, use the production application path with deterministic fixtures. Do not fabricate a successful live result.

Computer Use is secondary and limited to desktop-level checks that the browser surface cannot prove efficiently:

- actual macOS window rendering;
- long limitations, badges, and scrolling are not clipped;
- refresh/back/re-entry behavior remains visually coherent.

No account, credential, brokerage, or transaction interaction is part of acceptance.

## 15. Definition of Done

The subproject is complete only when:

- core routing and eligibility no longer depend on the `NO_DATA_AVAILABLE` sentinel;
- global statement routes are reachable under default configuration;
- OHLCV contains no future backward fill;
- all six horizon/market closure combinations pass;
- missing official/fundamentals evidence produces a transparent limited report;
- top-level stance is deterministically forced to `insufficient_evidence` when a core required capability is unavailable;
- provider outage, symbol non-coverage, unsupported capability, and invalid data are distinguishable;
- durable artifact replay produces the same Reader state;
- no new automated-test regressions are introduced;
- in-app browser and desktop acceptance pass;
- documentation matches the implemented contract.

## 16. Deferred work

The following are intentionally separate follow-on designs:

1. SEC submissions and filing-document integration.
2. Atomic `EvidenceItem` and claim-to-source-span validation.
3. Mandatory structured Analyst methodology contracts.
4. Claim-level debate and `DebateDigest` publication.
5. Deterministic confidence calibration.
6. ResearchMemory and learning cards.
7. Cross-model capability probing and cross-model evaluation, explicitly deferred by user request.
