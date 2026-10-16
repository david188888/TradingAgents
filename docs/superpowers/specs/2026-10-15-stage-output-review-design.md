# Independently readable saved stage outputs

- **Status: Frozen Design**
- 日期：2026-10-15。

The user approved this scope in chat on 2026-10-15: evidence and all research
stages should expose saved, independently qualified output while the run is
still in progress. A stage proposal is explicitly provisional until publication.

## Purpose and invariants

- Show actual facts, sources, dates, checks, hypotheses, challenges and replies.
- Execution completion, readable saved output and final publication are separate.
- Read only at a captured event sequence; never retrieve data, invoke models,
  execute checks, persist reconstructed records or rewrite historical artifacts.
- Keep current final-record publication and historical published-role validation.
- Validate seed identity/shape/source qualification, accepted proposal indices,
  evidence references and numeric receipts before exposing any stage body.
- Missing, unreadable, unsupported and invalid outputs remain distinguishable.

## Design

Add a `stage_available` availability and an optional closed `stage_record` to the
selected-role DTO. A stage record uses the existing public research schema with
no assessment. It carries only validated saved evidence and the prerequisites
needed to explain the selected proposal. It is never a final-report fallback.

A dedicated read-only projection validates the facts-only seed independently
of final publication. Specialists qualify against their frozen role partition,
preserving accepted original indices. Challenge/reply prerequisites are rebuilt
from qualified cached proposals and compared with saved verification frontiers
when present. Verification output is admitted only with matching saved input,
plan and output digests. Replies retain exact assignment and fact scopes.
Synthesis uses its saved pre-publication assembled output when present, with the
existing binding checks; until then it must pass independent reference checks.
One invalid specialist does not hide unrelated valid specialists or evidence.
Unknown workflows and corrupt bindings remain closed.
The new stage policy explicitly supports V7; older workflows keep their frozen
published-output behavior. Numeric catalogs and reference scope are rebuilt from
qualified prerequisites before receipt replay. A corrupt existing published
record/output is not publication absence and never triggers the stage fallback.

Process summaries report independent readability and an event sequence that
changes when the saved material changes. They never include stage bodies. The
selected-role endpoint alone includes actual content, on demand.

The existing adjacent detail view will show results first, with explicit
provisional labels, saved facts and source details, and fixed checks with their
limited scope. Generic role instructions and JSON move below the results.
Evidence links work before publication using the stage record; published-record
navigation retains its current behavior. Preserve keyboard focus, narrow layout
and reduced-motion behavior.

## Validation

The user additionally approved fixing process-dependent numeric final-field
validation: compare unique field-path bindings exactly, reject duplicates and
missing/changed bindings, emit stable new lists and preserve historic bytes.

Replay 600418 run `run_20261015T063526060533Z_c8e16c69` at sequence 144: evidence
must show its 132 facts, 79 source records and saved checks before sequence 285
publication. Exercise specialists, challenges, checks, replies and synthesis at
their saved boundaries; verify malformed/cross-scope/tampered inputs are hidden,
future boundaries rejected and no reads write or invoke research. Run scoped
Python, frontend, browser, docs and build checks and preserve generated assets.
