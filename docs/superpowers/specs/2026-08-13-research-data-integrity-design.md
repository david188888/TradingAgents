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
6. Data that cannot be attributed safely to the requested instrument must stop publication of substantive claims. The system may still publish a typed safe failure shell with public remediation guidance.
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
Initial Horizon Policy and cutoff-resolution policy
  -> deterministic verified-identity preflight
  -> frozen analysis_cutoff_at
  -> time-sensitive deterministic provider attempts
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
  analysis_cutoff_at
  availability
  freshness
  coverage
  source_ids[]
  attempts[]
  fallback_from[]
  effective_period
  published_at_or_filing_at?
  source_observed_at?
  fetched_at
  degradation_codes[]
  limitations[]
```

`capability_result_id` is the SHA-256 of canonical JSON over all semantic fields shown above; the ID itself is excluded from its hash input. Artifact ID, checkpoint committed sequence, event sequence, run identity, `captured_at`, and `committed_at` belong to the durable publication envelope created after prefetch, not to the semantic result, which avoids circular content addressing.

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

Coverage remains represented by the existing `BundleCoverageV1` and its `complete | partial | unknown | unavailable` completeness contract. Separating availability, freshness, and coverage prevents impossible single-enum compromises such as losing the fact that a dataset is both complete for its requested historical window and stale relative to the current run. Eligibility consumes both typed capability status and coverage; it must not infer the reason for `unavailable` from coverage alone.

Normative crosswalk:

| Availability | Allowed coverage | Required interpretation |
|---|---|---|
| `available` | `complete` | Usable payload exists and the requested-versus-observed extent is proven complete. Freshness is `current` or `stale`. |
| `partial` | `partial` or `unknown` | Usable payload exists, but either an observed gap is known or coverage cannot be proven. Freshness is `current`, `stale`, or `unknown`. |
| `not_covered` | `unavailable` | All sources in the negative-conclusion attempt set were observed and authoritatively reported non-coverage. |
| `not_supported` | `unavailable` | No implemented producer exists for the required capability/source contract. |
| `provider_unavailable` | `unavailable` | Required observation was prevented by outage, authentication, throttle, timeout, cooldown, or exhausted attempt budget. |
| `invalid` | `unavailable` | A payload was observed but failed identity, schema, period, or integrity validation. |

Every non-payload availability (`not_covered`, `not_supported`, `provider_unavailable`, `invalid`) requires `freshness=unknown`; freshness describes usable data, not the recency of an attempt. Zero-item negative outcomes are represented durably by `CapabilityResultV1` and its attempt records. `SourceCoverageV1` continues to describe source coverage and uses `completeness=unavailable` plus stable degradations for zero-item records; it is not asked to encode the negative cause by itself.

### 5.2 VendorAttemptOutcome

Provider routing uses a typed attempt outcome instead of a public sentinel string:

- `observed`
- `not_covered`
- `provider_failed`
- `not_supported`
- `invalid_payload`
- `skipped_unobserved`

Each outcome retains the provider, source identity, attempt/call identity, stable reason code, start/end timestamps, and artifact/provenance linkage when present. The canonical durable capability artifact contains one attempt record for every attempted or skipped eligible source. Negative and skipped outcomes are persisted even when no usable payload exists.

Legacy text-returning tools may render these outcomes at their boundary. Core routing, bundle construction, Registry, and eligibility must consume typed state.

## 6. Deterministic aggregation rules

1. A required source or source group that returns schema-valid data and satisfies its requested coverage produces `available`.
2. Usable data with incomplete coverage produces `partial`.
3. `not_covered` is allowed only when every source in the capability's **negative-conclusion attempt set** was actually attempted and returned authoritative non-coverage. For a direct required source, the set contains that source. For an any-of source group, it contains every eligible group member until one satisfies the group or all members return authoritative non-coverage. Optional sources are excluded.
4. Any required provider that remains unobserved because of outage, authentication, rate limiting, timeout, or cooldown prevents a `not_covered` conclusion and produces `provider_unavailable` unless another accepted source group independently satisfies the capability.
5. A capability without an implemented producer produces `not_supported` with a stable reason code.
6. A payload that violates schema, identity, period, or integrity requirements produces `invalid`.
7. When an accepted fallback independently satisfies the full source requirement, the capability may be `available`; the failed primary remains visible through `fallback_from` and provenance.
8. Optional source failure does not lower a fully satisfied required source group.
9. Fetch budgets must permit exhaustion of the negative-conclusion attempt set when a `not_covered` conclusion is desired. If budget is exhausted first, remaining sources are durably recorded as `skipped_unobserved` and the aggregate is `provider_unavailable`, never `not_covered`.

### 6.1 Canonical artifact selection

A run may commit retries, but a Research Case must not reselect evidence during replay. The publisher enforces at most one capability result for a capability at any one checkpoint committed sequence. For each capability, the assembler selects the greatest eligible publication-envelope tuple `(committed_sequence, event_sequence, artifact_id)` whose committed sequence is less than or equal to the candidate Research Case source sequence. It then persists the selected artifact ID, semantic `capability_result_id`, evidence refs, and coverage refs in the case publication input. Reader replay consumes those persisted selections rather than asking the Registry to choose the first artifact again.

## 7. Cache and historical-date semantics

When a live source is unavailable but a compatible last-good artifact exists:

- the result may remain `available` or `partial`;
- freshness becomes `stale`;
- actual source and `fetched_at` remain visible;
- decision eligibility is capped at `limited` for a stale required capability;
- the cache must be compatible with the requested symbol, market, capability, period, price basis, and analysis-date boundary.

Time fields have distinct meanings:

- `effective_period`: fiscal or market period described by the fact;
- `published_at_or_filing_at`: when the issuer/source made the fact public;
- `source_observed_at`: provider-reported observation/event time;
- `fetched_at`: when TradingAgents requested the source;
- `captured_at`: publication-envelope time when the finalized semantic result was accepted for durable capture;
- `committed_at`: publication-envelope time when the durable artifact/event commit completed.

Cutoff resolution is two phase. The pure initial horizon plan declares a versioned cutoff-resolution policy but does not claim a verified global timezone. A deterministic verified-identity preflight runs first. Code then resolves and freezes timezone-aware `analysis_cutoff_at` before any time-sensitive provider filtering. A-share uses end-of-day in `Asia/Shanghai`. Global instruments use the verified primary exchange timezone and applicable market calendar; if that timezone cannot be established, time-sensitive required capability status is `invalid`. The resolved cutoff and identity reference are persisted with the durable run plan and selected result envelopes. All timestamps are normalized to UTC before comparison.

A historical run must not use a fact whose publication/filing availability or applicable source event/observation time is after `analysis_cutoff_at`. `fetched_at` or `captured_at` after the cutoff is not by itself proof of future leakage, but a mutable endpoint fetched later may satisfy historical coverage only when a preserved point-in-time record proves the payload was public by the cutoff. Unknown publication/filing availability cannot satisfy a required historical fundamentals or official-disclosure capability. Restated statements must retain both original and restatement publication identity; a restatement published after the cutoff is safely excluded from the historical view and degrades coverage.

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

The bundle records statement type, fiscal period, publication/filing date, requested and observed windows, source, units, currency, all five time semantics, attempt outcomes, and limitations. Unknown publication/filing date can be displayed as limited evidence for a current run but cannot establish required historical coverage.

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
  -> typed capability-status consumer
  -> eligibility consumer
```

The invariant is tested for all three horizons and both supported market kinds.

## 10. Eligibility and publication

The existing report remains publishable when data is missing.

- All implemented required capabilities complete/current and the Evidence Gate permits publication: eligibility may be `full`, except in policy cells with an intentionally unsupported required capability.
- A required capability that is partial or stale: eligibility is at most `limited`.
- A required capability that is `not_covered`, `not_supported`, `provider_unavailable`, or `invalid`: the report remains publishable, but the top-level stance is forced to `insufficient_evidence`.
- Optional capability failure affects only related limitations and claim confidence.
- A model-provided stance or confidence cannot upgrade deterministic eligibility.

`assess_decision_eligibility` returns the eligibility, data quality, a forced top-level rating when applicable, and deterministic missing-capability actions. Final case assembly applies this result after parsing the model draft and overrides any incompatible model rating. For every unavailable required capability, assembly creates or merges a code-owned `unknown` and review action from a versioned capability/reason mapping. `ResearchCaseV2` validates that unavailable required capability results cannot coexist with a rating other than `insufficient_evidence`.

Existing verified claims remain visible. The model cannot omit or rewrite the code-owned missing-capability reason and next validation action.

`FAIL_STOP` is reserved for cases where safe attribution or temporal integrity is impossible, including:

- instrument identity conflict;
- evidence observed after the analysis-date boundary;
- corrupted artifact/hash or cross-run evidence linkage;
- payload identity that cannot be associated safely with the requested instrument.

Registry and runner errors are divided into recoverable absence and typed fatal integrity failures. A post-cutoff candidate record detected before selection is safely excluded and degrades coverage. Post-cutoff evidence already selected, registered, or linked into a public fact is a temporal-integrity violation. Corrupted artifact/hash, cross-run identity/linkage conflict, instrument conflict, and temporal-integrity violations are not skipped and cannot fall through to the generic partial-case fallback. They propagate to a safe public `FAIL_STOP` shell that withholds substantive claims and exposes only stable public reason codes and remediation guidance.

## 11. Compatibility and migration

- Public Reader schema major is unchanged.
- Existing completed runs and durable Reader artifacts are not rewritten.
- Existing state bundle keys continue to carry canonical JSON strings.
- `CoveredText` and legacy text-returning tools remain available at compatibility boundaries.
- New typed metadata is added within versioned bundles and is rendered to text only at legacy boundaries.
- Any new public `ResearchCaseV2` field is additive with a legacy-safe default, or is introduced behind a versioned parser path. A golden pre-change serialized `ResearchCaseV2` artifact must continue to open in Reader.
- The implementation does not change Analyst count, debate order, prompts, model/provider selection, or Reader layout.
- Python and semantic data-contract changes must invalidate incompatible checkpoints through the existing fingerprint mechanism. Methodology-asset fingerprinting belongs to a later subproject.

The current uncommitted changes to `research_manager.py`, `DecisionBrief.tsx`, workbench CSS, and built web assets are outside this subproject and must not be overwritten or folded into its commits.

## 12. Implementation increments

### Increment A: contract and state-transition tests

- Introduce typed capability and provider-attempt contracts.
- Add deterministic aggregation functions.
- Add deterministic verified-identity preflight and freeze `analysis_cutoff_at` before time-sensitive fetch/filter steps.
- Persist per-source attempts and contract-required availability, freshness, time fields, actual provider, and fallback metadata.
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
- Persist the bundle, typed attempts, time semantics, and capability result as an evidence artifact.
- Make Analyst access reuse the frozen current-run result.

### Increment D: official disclosure coverage

- Register existing A-share official evidence with typed attempts and time semantics.
- Emit and persist explicit `not_supported` global coverage until SEC integration exists.

### Increment E: Registry and eligibility closure

- Register every required capability.
- Select the latest eligible committed artifact per capability and persist the selection into case publication input.
- Propagate fatal integrity results instead of skipping them or publishing the generic partial fallback.
- Add closure tests.
- Enforce the top-level `insufficient_evidence` cap.

### Increment F: audit presentation and documentation

- Expose already-recorded typed provenance in the audit presentation where safe.
- Update the learning research and data-capability documentation.

## 13. Test strategy

### 13.1 Unit tests

- Provider attempt to capability result transitions.
- No-data versus unobserved-provider distinctions.
- Fallback source preservation.
- Stale-cache and historical-date rules.
- Contract validation and stable reason codes.
- Coverage/availability crosswalk, including `coverage=unknown`.
- Availability/freshness validation, including rejection of non-payload states marked `current` or `stale`.
- Negative-conclusion budgets and skipped-unobserved sources.

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
- Market-timezone `analysis_cutoff_at` derivation and UTC comparison.
- Unknown-date news excluded from coverage.
- Fiscal period, filing date, and analysis date remain distinct.
- Restatements after the historical cutoff are excluded.
- Unknown filing dates do not satisfy historical required coverage.

### 13.4 Policy closure matrix

Parameterize:

```text
short | medium | long
x
a_share | global
```

Test a complete fixture where the policy cell is implementable, a partial/stale fixture, a required-unavailable fixture, an identity-conflict fixture, an artifact-corruption fixture, a cross-run-linkage fixture, and a post-cutoff fixture.

Expected results:

- A-share short/medium/long and global short: a complete fixture makes `full` reachable when all other eligibility conditions pass;
- global medium/long: `official_disclosures=not_supported`, eligibility is `limited`, and rating is `insufficient_evidence`; no fake SEC-complete fixture is allowed;
- partial/stale -> at most `limited`;
- required unavailable -> run completes and stance is `insufficient_evidence`;
- safely filterable post-cutoff candidate record -> excluded and coverage degraded;
- identity, corruption, cross-run linkage, or already-selected post-cutoff evidence -> `FAIL_STOP` safe shell with substantive claims withheld.

### 13.5 Regression checks

After each increment run:

- focused unit tests;
- relevant dataflow/research/graph integration tests;
- tracked Reader contract tests;
- full pytest compared with the recorded pre-change baseline;
- Ruff;
- frontend typecheck and existing tests.
- pre-change serialized `ResearchCaseV2` Reader golden.

The pre-change workspace has known failures. Completion requires no new failures, all subproject tests passing, and related old failures fixed where the changed behavior supersedes them. Network-, credential-, and sandbox-dependent failures must be reported separately rather than hidden.

## 14. Browser and desktop acceptance

Use the user-requested in-app browser as the primary UI interaction surface. Validate:

1. Use the production application path with a deterministic acceptance fixture that injects a named required-provider outage or cooldown into an A-share medium company research run.
2. Inspect data progress and confirm the injected provider failure identity.
3. Open the completed Reader.
4. Verify `insufficient_evidence`, missing reasons, and next validation actions.
5. Verify supported local facts remain readable.
6. Refresh and reopen the run to verify durable replay.
7. Inspect Audit Center to ensure outage/cooldown is not rendered as company non-coverage.
8. Check browser console, failed requests, and initial DOM for regressions or sensitive debug leakage.

Run any credentialed live analysis separately as a smoke check; it is not the deterministic acceptance oracle. Do not fabricate a successful live result.

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
