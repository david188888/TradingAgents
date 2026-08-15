---
name: evidence-bound-research-interoperability
description: Route a company research question to an existing run, research package, reader projection, and evidence anchors without inventing data or issuing trading instructions.
roles:
  - research_manager
triggers:
  - a user asks to analyze a company, ticker, metric, peer comparison, logic edge, claim, evidence, or prior question
  - an Agent needs to resume a run from a manifest, research package, or reader projection
output_schema:
  - company_name
  - ticker
  - question
  - run_id
  - package_sha256
  - referenced_anchors
  - answer_evidence_refs
  - availability
---

## Request parsing

First extract a bounded request object from the user's visible message:

```json
{"company_name": "optional Chinese or English name", "ticker": "optional code", "question": "required question", "run_id": "optional explicit run"}
```

Preserve the user's question verbatim for the answer context. A six-digit A-share
code may be normalized to the repository ticker form only when an existing run
or package confirms the exchange; do not guess an issuer from a name alone.
`run_id` is optional input, never a value to invent. `analysis_cutoff` is a
date-level value from the selected package/manifest; do not manufacture a
timestamp or silently use today's date.

## Deterministic lookup order

1. If `run_id` is supplied, read that run first and reject it when its snapshot
   ticker conflicts with a supplied ticker/company identity. Otherwise list
   recent runs through `GET /api/runs?view=recent` (or the configured local
   RunStore) and match the normalized ticker. A company name match is only a
   candidate until the run/package ticker confirms it. If more than one run
   remains, prefer the latest completed run with a public package; otherwise
   ask the user to choose a `run_id` and show the candidate tickers/dates.
2. For the selected run, load `GET /api/runs/{run_id}/reader/package`.
   This is the factual package and must validate as `research-package-v1`.
   Record `package_sha256` as the canonical hash of the package JSON. The
   repository provides `package_sha256` (and `canonical_json_bytes`) in
   `tradingagents.research.public_hash`; use the same canonical public
   projection when verifying an external copy of the package.
3. Load `GET /api/runs/{run_id}/reader` for the public reader projection. Use
   its `claims`, `analyst_cards`, `thesis_diff`, and review/omission fields only
   as public projections; cross-check any claim's `evidence_ref_ids` against
   package evidence refs before treating it as supported.
4. Read a requested evidence ref only through
   `GET /api/runs/{run_id}/evidence-refs/{ref_id}`. Follow its returned
   `read_url` only for the same run and only after the ref is resolved.
   `GET /api/runs/{run_id}/reader/companion?kind=claim|evidence|role|risk&id=...`
   is the stable detail path for a selected reader item.
5. Answer the question directly from the selected package, reader projection,
   and resolved evidence. TradingAgents does not host a local conversation
   thread API: question/answer context lives in the external Agent session
   (Proma, Codex, etc.), and every answer is re-derived from the current public
   fact layer rather than an append-only transcript. The server-side
   `research-package-v1` and reader projections are the only lookup
   authorities; do not scan run files directly.

## Stable public paths

Use these identifiers as anchors, not display text or array positions:

- metric definition: `metric:{metric_id}` from `metric_definitions[*]`
- metric observation: `observation_id` from `observations[*]`
- formula result: `evaluation_id` from `formula_evaluations[*]` and its output observation
- peer set: `peer_set_id` from `peer_sets[*]`
- peer comparison: `comparison_id` from `comparisons[*]`
- logic edge: `edge_id` from `logic_edges[*]`; include its `status`, `missing_evidence`, and `next_validation`
- evidence: `evidence_refs[*].ref_id`, then the evidence-ref endpoint
- claim: the reader's stable claim key/id, then the companion claim endpoint; include its evidence refs

For every factual answer, cite the selected `run_id`, package schema/version
and `package_sha256`, plus at least one applicable anchor. A metric answer
needs its observation/evaluation and metric definition; a peer answer needs
the peer set and comparison; a logic answer needs the edge and all listed
evidence refs; a claim answer needs the claim key and its evidence refs. A
historical comparison must cite the `thesis_diff` item as well as the current
package anchor.

## Missing data and clarification

Ask one focused clarification when the company identity is ambiguous, such as
"请提供公司股票代码（如 `600519.SH`）或确认公司名称，以及要查询的报告期/运行 `run_id`。"
Ask a second focused clarification when the question is underspecified, such
as whether the user wants metrics, peers, logic edges, claims, or evidence. Do
not ask for information already present in the selected run/package.

Return `availability: unavailable` when the run, package, requested anchor, or
provider-backed value is missing, invalid, cross-run, or explicitly marked
unavailable. Include the stable reason (`research_package_unavailable`,
`anchor_not_found`, etc.) and the next public validation step. Do not
substitute a different company, run, period, or metric. Preserve package
unknowns and observation/comparison unavailable reasons verbatim.

## Answer boundary

Separate observed/derived package facts, reader claims, and the model's cautious
interpretation. Never turn a research rating, scenario, edge, or conclusion
into a buy/sell/hold instruction, target price, allocation, timing command, or
personalized investment advice. This is a learning research interface only.

The external Agent session owns the dialogue context. Never persist or export
prompts, raw tool arguments or results, credentials, private reasoning, hidden
reasoning, or unrelated run state. This method describes routing and citation
behavior only; it does not add tools, network access, provider authority, or
execution authority.
