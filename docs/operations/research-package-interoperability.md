# Research Package Interoperability

Status: Current — this page documents the isolated public conversation/export
boundary. The machine-owned models are in
`tradingagents/research/conversation_models.py`, and the append-only file
implementation is in `conversation_store.py`.

## Boundary

A conversation is anchored to one `run_id` and one public research-package
schema/hash. It stores only a user question, an assistant answer, public
anchors, evidence reference IDs, availability, refusal reason, and next public
validation steps. The store does not accept prompts, raw tool arguments or
results, credentials, hidden reasoning, or arbitrary run state.

Each thread starts with a validated header and appends messages with contiguous
sequence numbers. Repeating the same message at an existing sequence is
idempotent; a different duplicate or a sequence gap is a conflict. Existing
run history and research artifacts are not rewritten.

## Portable bundle

`export_research_bundle()` writes a new directory containing:

- `manifest.json`: export schema, run/thread/package anchors, analysis cutoff,
  data quality, non-trading boundary, and SHA-256/byte-size metadata for every
  other file.
- `research-package.json`: machine-readable public package projection.
- `research-package.md`: readable projection with the same public JSON.
- `metric-dictionary.json`: optional public definitions.
- `sources.json`: optional public source metadata.
- `conversation.jsonl`: the thread header followed by messages in sequence.

The exporter recomputes the package hash and refuses a mismatch. A destination
must be new or empty; it never overwrites an existing export.

## Agent consumption

The bundled `evidence-bound-research-interoperability` Skill is the routing
contract for Proma/Agent consumption. It parses the visible request into
`company_name`, `ticker`, `question`, and optional `run_id`, then follows this
order:

1. Resolve an explicit `run_id`; otherwise query `/api/runs?view=recent` or the
   local RunStore and match a confirmed ticker. A name-only match is a
   candidate, not an identity. Ambiguous candidates require a clarification.
2. Read `/api/runs/{run_id}/reader/package` and validate
   `research-package-v1`. For an export, verify all `manifest.json` file hashes
   and the package hash before reading `research-package.json`.
3. Use `/api/runs/{run_id}/reader` for public claims, analyst cards, omissions,
   and `thesis_diff`; use `/reader/companion` for stable selected claim/evidence
   details and `/evidence-refs/{ref_id}` for evidence resolution.
4. Resolve metrics, observations, formula evaluations, peer sets,
   comparisons, and logic edges by their package IDs, never by array position.
   The canonical anchor forms are documented in the Skill and include
   `metric:{metric_id}`, `observation_id`, `evaluation_id`, `peer_set_id`,
   `comparison_id`, `edge_id`, and `evidence_refs[*].ref_id`.
5. Restore conversation history through the local thread API:
   `GET /api/runs/{run_id}/threads` lists threads,
   `GET /api/runs/{run_id}/threads/{thread_id}` reads one, and
   `POST /api/runs/{run_id}/threads/{thread_id}/messages` appends a public
   question/answer pair. Export through
   `GET /api/runs/{run_id}/threads/{thread_id}/export` and verify the returned
   ZIP manifest before consuming `conversation.jsonl`. The JSONL files under
   `~/.tradingagents/web/runs/{run_id}/conversations/thread_*.jsonl` are the
   storage implementation only; an absent thread is explicitly unavailable,
   not evidence that an answer is false.

Every answer binds to one `run_id` and package SHA-256, and cites the relevant
stable anchors plus evidence ref IDs. `analysis_cutoff` is consumed as a date,
not a fabricated timestamp. Missing or invalid data produces an explicit
`unknown`/`unavailable` result with a reason and next public validation step;
the Agent must not substitute another company, run, period, or metric.

Claims and reader prose do not upgrade unsupported package facts. Keep unknowns
explicit; the package is for learning research and is not a trading instruction.

The TradingAgents Skill registry exposes this method only to the statically
mapped `research_manager` role. A Skill is a behavior contract, not a session
database and not a Proma/Codex credential or transport binding.
