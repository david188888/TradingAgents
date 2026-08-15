# Research Package Interoperability

Status: Current — this page documents how an external Agent (Proma, Codex,
etc.) consumes a completed TradingAgents run through the public research-package
and reader fact layer. The machine-owned package contract lives in
`tradingagents/research/research_package.py`; canonical public hashing lives in
`tradingagents/research/public_hash.py`.

## Boundary

TradingAgents does not host a local conversation thread API and does not store
question/answer transcripts. The server exposes a read-only fact layer:

- `GET /api/runs` (and `?view=recent`) lists runs for identity resolution.
- `GET /api/runs/{run_id}/reader/package` returns the validated
  `research-package-v1` projection for one run.
- `GET /api/runs/{run_id}/reader` returns the public reader projection with
  claims, analyst cards, `thesis_diff`, and review/omission fields.
- `GET /api/runs/{run_id}/reader/companion?kind=...&id=...` returns stable
  detail for a selected claim/evidence/role/risk item.
- `GET /api/runs/{run_id}/evidence-refs/{ref_id}` resolves one evidence ref.

The dialogue context belongs to the external Agent session. Every answer is
re-derived from the current public fact layer, never from an append-only
transcript. Prompts, raw tool arguments or results, credentials, hidden
reasoning, and unrelated run state never cross this boundary.

## Canonical package hashing

`package_sha256(package)` and `canonical_json_bytes(package)` in
`tradingagents/research/public_hash.py` compute a deterministic SHA-256 over the
public JSON projection. The canonical form rejects private fields before
hashing, so the digest never depends on non-public payloads. An external Agent
records `package_sha256` as the anchor for every factual answer and uses the
same canonical projection to verify any external copy of the package.

## Agent consumption

The bundled `evidence-bound-research-interoperability` Skill is the routing
contract for Proma/Agent consumption. It parses the visible request into
`company_name`, `ticker`, `question`, and optional `run_id`, then follows this
order:

1. Resolve an explicit `run_id`; otherwise query `/api/runs?view=recent` or the
   local RunStore and match a confirmed ticker. A name-only match is a
   candidate, not an identity. Ambiguous candidates require a clarification.
2. Read `/api/runs/{run_id}/reader/package` and validate
   `research-package-v1`. Record `package_sha256` via
   `tradingagents.research.public_hash`.
3. Use `/api/runs/{run_id}/reader` for public claims, analyst cards, omissions,
   and `thesis_diff`; use `/reader/companion` for stable selected claim/evidence
   details and `/evidence-refs/{ref_id}` for evidence resolution.
4. Resolve metrics, observations, formula evaluations, peer sets,
   comparisons, and logic edges by their package IDs, never by array position.
   The canonical anchor forms are documented in the Skill and include
   `metric:{metric_id}`, `observation_id`, `evaluation_id`, `peer_set_id`,
   `comparison_id`, `edge_id`, and `evidence_refs[*].ref_id`.
5. Answer the question directly from the selected package, reader projection,
   and resolved evidence. TradingAgents does not host a conversation thread
   API; the external Agent session owns question/answer context, and the
   public fact layer is the only lookup authority. Do not scan run files
   directly.

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
