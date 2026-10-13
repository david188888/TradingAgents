# Luna company research E2E repair

Status: Historical — Do not use this document as evidence of current implementation behavior.

Current behavior belongs to the unified research contract and Web evidence operations;
the [E2E investigation](../../reviews/2026-10-13-luna-e2e-offline-diagnosis.md) records the
remaining real synthesis failure and the user's zero-call offline diagnosis boundary.

The user approved timestamped intraday prices, a cautious overall judgement when
the value range is missing, and corrections restricted to real related saved
evidence on 2026-10-13. Baseline run
`run_20261013T033927051053Z_4f4bc126` published a partial record with 72 sources,
but its synthesis failed dimension reference validation twice.

## Scope and alternatives

Use the existing native evidence, proposal, validation and Reader path. Extend
current-date snapshot admission and make the model's reference choices smaller
and explicit. Preserve the public schemas and strict rejection of invented or
unrelated references. A separate manually written report would not verify the
product. Removing reference validation would break traceability. Neither is used.

## Price and history

For a fresh current-cutoff run, accept either the last settled session snapshot
or a current-session quote captured no later than the collection time. A live
quote requires a timezone-aware capture time, matching security, positive price,
turnover and market cap, and a valid PB or PE. Reject future timestamps, other
dates and historical-cutoff live data. Preserve the actual quote date/time; do
not label it yesterday's close. Mark current-session intraday inputs explicitly.
Peer quotes must use the target snapshot's date. Historical multiples retain
their own date and may end before the snapshot date; use only admitted rows at
or before that snapshot. Never fabricate an earnings or intrinsic-value anchor.

## Judgement

Qualified operating support remains necessary. Missing valuation inputs or a
reference range prohibit favorable, but allow neutral/unfavorable conclusions
with qualified referenced reasons and explicit valuation uncertainty. Keep
insufficient_evidence when operating support or valid reasons are absent.
Dimensions retain their own evidence ceilings and the public record validator
continues to reject unrelated, unavailable, withdrawn or fabricated references.

## Model references

Fresh prompts use reversible host aliases for specialist facts, sources and
metrics as well as synthesis. The schema shown in each fresh prompt enumerates
the actual allowed facts, dimension claims and valid conclusion claims in that
context. The host restores canonical IDs and repeats the original validation.
Compact synthesis source content to saved source metadata; preserve complete
qualified fact statements, hypotheses, challenges, code observations and replies.
No silent deletion of invalid references while keeping an unsupported narrative.
Each fresh prompt freezes its policy in checkpoint keys; previously saved
prompts/caches retain their original identities, with no historical rewrite or
unknown-request replay. Existing repair/request budgets and cancellation stay.

## Verification and delivery

Add meaningful regression tests for intraday/future/stale quotes, history versus
quote date, missing-range cautious judgement and rejected favorable judgement,
role-local reversible aliases, enumerated prompt reference scopes and historical
prompt recovery. Run native/model/valuation/Reader suites, Ruff and docs checks.
Rebuild frontend assets only if source changes become necessary. After checks,
restart the authorized 8765 service with no active run and run a fresh Chinese
600418.SS research using ChatGPT gpt-6-luna for both selectors. Verify saved
specialists, challenges/replies, synthesis, Reader evidence links and the actual
published report. Preserve pre-existing dirty work and user records; no Git
publication or Hindsight operations are authorized.
