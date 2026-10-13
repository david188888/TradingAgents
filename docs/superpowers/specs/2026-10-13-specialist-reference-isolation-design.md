# Specialist reference isolation

Status: Historical — Do not use this document as evidence of current implementation behavior.

Current behavior is documented in [Web evidence research](../../operations/evidence-research.md)
and the [documentation index](../../README.md).

The user approved this design on 2026-10-13. It completes PR #28 defect D on
the real SDK adapter path without widening evidence scopes.

## Behavior

New V7 runs freeze `specialist_reference_policy=bounded-repair-then-isolate-v1`
in their checkpoint identity. Older identities retain existing adapter behavior.
After JSON and full proposal schema validation, a shared validator partitions
hypotheses by fact, condition-evidence and condition-metric reference validity.
Malformed JSON/schema is never partially admitted.

A mixed main response receives the existing single structured repair opportunity.
If repair succeeds, use that complete repaired proposal. If repair fails with
model-output/request unavailability or the repair budget is refused, use only
the validated hypotheses from the original main response. Never combine main
and repair hypotheses. Cancellation, deadline and checkpoint failures do not
trigger fallback. No valid hypotheses means that specialist is unavailable.

## Persistence and identity

Before repair, persist only a schema-valid, reference-valid main candidate, its
original hypothesis indices, closed rejection codes and prompt digest. Rejected
statements and fabricated references are never accepted or cached as proposals.
Persist acceptance metadata bound to the exact accepted proposal. Retain original
indices for deterministic hypothesis IDs. Successful repair clears main-response
rejections from the final output, while safe attempt diagnostics remain.

Read-only recovery may use the saved valid candidate when the original main
dispatch and its validated content are known; it never repeats an
unknown dispatch. A saved valid repair takes precedence. Unknown policies or
invalid metadata fail as checkpoint incompatibility. Old prompts and identities
remain unchanged; historical records are not rewritten.

## Kernel and projections

The kernel revalidates every accepted hypothesis with the same validator, records
role/index/closed reason for dropped hypotheses, and forces partial/LOW_CONFIDENCE
when any effective proposal was rejected. Empty filtered specialists are explicitly
unavailable. Claims, conditions, challenges, replies and synthesis receive only
accepted hypotheses. Existing Reader and Markdown limitation labels describe
the rejection. The public failure category remains evidence_rejection; typed
reference errors distinguish fact/evidence/metric causes without exposing raw
model responses or broadening missing_configuration handling.

## Validation and implementation order

1. Shared typed validation and checkpoint policy identity/resume guards.
2. Durable candidate, bounded repair fallback and read-only cache recovery.
3. Kernel metadata binding, original indices, partial status and readable labels.
4. Mock-SDK mixed responses, successful repair, invalid repair, refused budget,
   all-invalid output, malformed JSON/schema, cancellation/deadline, crash/cache
   recovery, unknown dispatch, policy mismatch and old identity regression.
5. Kernel-to-published-record/Reader tests for rejected-reference exclusion and
   partial status; scoped Python suites, Ruff, agent docs and diff checks.

No live paid model calls, data cleanup, service restart or Git publication are
part of this implementation request.
