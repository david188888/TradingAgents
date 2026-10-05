# Low-cost evidence implementation

Status: Historical

Do not use this document as evidence of current implementation behavior.
Current references: [documentation index](../../README.md).
Approved direction: [design](../designs/2026-10-05-low-cost-evidence-design.md).
Spec review: Approved on 2026-10-05; user confirmed and requested implementation.
Implemented locally. Actual public-source/fixed-proposal acceptance is recorded
in [the acceptance snapshot](../../reviews/2026-10-05-minimum-evidence-acceptance.md).
Paid-model quality acceptance and remote publication were not part of this run.

## Delivery tasks

1. **Frozen contracts and deterministic checks (5 points; prerequisite).**
   Add versioned official numeric rows, dated forecasts/peer context and closed
   local check artifacts. Optional fields preserve old serialization. Assessment
   v2 outcomes are code-owned and recomputed with their input bindings.
   Acceptance: hash/identity/date/unit/arithmetic/outcome tampering rejects;
   missing optional inputs never suppress a passed bounded check.
2. **Official PDF v2 admission/extraction (5 points; depends on 1).**
   Keep v1 parser untouched. Recognize prefixed report/summary/operating notice,
   verify issuer/security/period, retain bounded relevant excerpts and explicit
   financial pairs, operating rows and adjacent-page cash bridge.
   Acceptance: actual 600803 title/header/physical-unit/H1-Q2 cases; current/prior
   CFO bridge matches official totals; unsupported layouts remain unavailable.
3. **Bounded supplemental collector (5 points; depends on 1–2).**
   New v5 collector uses existing BudgetedSession/durable calls. Dated THS
   institution rows, explicit-year EastMoney fallback, bounded named industry
   candidates and one same-session Tencent quote request.
   Acceptance: dates, deduplication, missing values, exclusions, HTTP/data limits,
   cancellation and response-unknown controls; replay does not use transport.
4. **Workflow/model version dispatch (5 points; depends on 1–3).**
   New runs select v5. Old v1–v4 use original collector/schema/prompt/context.
   New critic selects immutable check scopes; synthesis cannot write outcomes.
   Acceptance: old recovery before collection, with seed, cached proposals and
   output; immutable old digests; challenged economics remain conditional/LOW.
5. **Reader/export projection (3 points; depends on 4).**
   Show answered scope, supporting basis and remaining economic uncertainty in
   existing Reader hierarchy. Keep old rendering; JSON/Markdown/HTML share the
   validated artifact. Rebuild tracked SPA.
   Acceptance: DTO/React tests, actual saved API/DOM view, no read-time fetch.
6. **600803 acceptance and documentation (3 points; depends on all).**
   Public-source ingestion with model transport disabled, deterministic fixture
   proposals clearly labelled in Web/HTML preview, focused then full available
   checks. Update current operations/contracts only after behavior is verified.
   Acceptance: evidence IDs/pages/units traceable, three local results visible,
   future/causal questions remain open, no additional paid SDK calls or remote
   publication, default user data untouched.

## Execution boundaries

Implement in the current checkout and preserve existing changes. No CLI work,
new runtime dependencies for external projects, free-form agent loop, OCR,
automatic grade promotion or copied external whole modules. Use root execution
for implementation; the skill-authorized spec review is complete. New mutable
probe/preview data stays under ignored output or `/private/tmp`.
