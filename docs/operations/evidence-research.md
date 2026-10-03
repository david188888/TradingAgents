# Explicit evidence-driven research trials

Status: Current

`evidence_v1` is an explicit A-share research profile with a shared native
evidence, hypothesis, challenge, verification and synthesis workflow. The Web
API routes it to `execution/native_runner.py:NativeRunner`. It is separate from
the existing `classic` and `catalyst_v1` execution and recovery paths. Omitted
profiles still use classic; the CLI and existing workbench forms keep their
defaults. No new profile or mode selector is added to the workbench.

## Start an API trial

Keep model/data credentials in ignored local configuration. Enable native
creation for the server process:

```bash
TRADINGAGENTS_EVIDENCE_ENABLED=true tradingagents web --port 8765 --open
```

`GET /api/config` reports support under `research_profiles.evidence_v1`. The
flag is independent of `TRADINGAGENTS_CATALYST_PROFILE_ENABLED`; it does not
switch the default profile. A disabled native creation request returns
`403 evidence_profile_unavailable`, without falling back to classic. Saved
native runs remain readable when creation is disabled.

Submit one run through `POST /api/runs`. This example contains no credentials;
replace the cutoff and model IDs with the values for the intended research and
the configured provider. A historical cutoff can leave price evidence
unavailable when its archive vintage cannot be established.

```bash
curl --fail-with-body http://127.0.0.1:8765/api/runs \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{
  "ticker": "600519.SS",
  "analysis_date": "2026-10-02",
  "research_profile": "evidence_v1",
  "mode": "company_research",
  "research_question": "哪些经营事实支持持续改善，哪些问题仍需核查？",
  "llm_provider": "deepseek",
  "quick_think_llm": "deepseek-v4-flash",
  "deep_think_llm": "deepseek-v4-flash",
  "output_language": "Chinese"
}
JSON
```

The optional question is trimmed and limited to 400 Unicode code points. It
is saved in run identity; omission uses the mode's code-owned question.
Native roles and the single challenge stage are code-owned. Omit classic
scheduling fields, or retain their compatibility defaults: all four analyst
keys, depth/rounds of one, and `horizon=medium`. Non-default selections are
rejected rather than ignored. The `evidence_policy` may be omitted; if supplied,
it must match `NativeEvidencePolicyV1`, not the catalyst policy.

| Mode | Research scope | Additional input |
| --- | --- | --- |
| `company_research` | Operating quality, valuation evidence and market context. | No holding context. |
| `catalyst_research` | Operating evidence, catalyst delivery and market context over the next 84 calendar days. | No holding context. This mode requires `evidence_v1`; the older `catalyst_v1` entry still uses `company_research`. |
| `holding_review` | Recheck the user's original thesis against operating, valuation and market evidence. | A `holding` object with ticker, positive quantity and average cost; other account facts and the original thesis remain optional. |

For holding review, change the mode and add user-provided facts. The following
is illustrative input, not an actual account or a suggested position:

```json
{
  "mode": "holding_review",
  "holding": {
    "ticker": "600519.SS",
    "quantity": 100,
    "average_cost": 10,
    "facts_as_of": "2026-10-02",
    "original_thesis": "原假设：收入改善能够延续；下一期收入回落则重新核查。"
  }
}
```

The full body retains the other fields from the company example. Holdings are
declarations, not independently verified evidence. Missing original thesis
limits the holding-thesis dimension; the system does not invent it or infer
missing account values. Company and holding modes do not acquire an 84-day
outlook from the collector's compatibility adapter.

## Evidence and workflow

The code-owned source policy fixes 7/30/90-day event windows, 250 trading days
of price history and eight financial-reporting quarters. Source windows are
separate from research outlook. The native runner reuses the bounded Tushare
identity/financial/price and CNINFO announcement collector, respecting the
configured vendor chain and cutoff qualification described in
[source qualification](catalyst-research.md#sources-and-qualification).
Having credentials does not establish entitlement, complete coverage or
point-in-time provenance. Opaque SDK sources and unqualified historical factors
remain unavailable; a source gap never proves an event did not occur.

```text
qualified saved source fields -> facts-only V0
  -> operating quality / event context / market context specialists
  -> one independent challenge stage (zero to three challenges)
  -> bounded condition verification (up to three checks)
  -> one dimension-gated synthesis -> authorized native record and Markdown
```

Facts and source identity are extracted by code. Specialists see isolated fact
views, with fixed reservation and merge order and at most two concurrent
workers. Context isolation is not statistical independence. Hypotheses cite
facts and retain invalidation conditions and alternative explanations. The
challenge stage sees anonymous hypotheses; it need not manufacture opposing
positions when evidence is clear.

Verification is a closed local operation on saved financial fields or metrics.
It is not an unrestricted model tool loop or additional data search. Checks
bind a hypothesis, challenge, immutable condition and input snapshot. Actual
checks create V1 lineage while preserving V0; zero execution creates no V1.
A successful predicate check does not prove the whole hypothesis or close an
economic challenge. Derived arithmetic retains its source family.

The synthesis follows code-owned dimensions and evidence ceilings. Unavailable
valuation inputs constrain valuation; missing qualified prices constrain market
context. Announcement titles do not establish delivery. The current source
adapters do not supply qualified valuation inputs to this native workflow, so
company and holding research retain an unresolved valuation dimension and a
partial assessment. Risk/ATR statistics do not fill that gap.

## Budget, cancellation and recovery

The native flow reuses the existing durable ledger and its hard limits: five
main model calls, two structured repairs across the run with at most one per
stage, and twelve model attempts in total. Data calls retain the existing
twenty-four capability and sixty-four HTTP-attempt ceilings. One bounded
verification round covers at most three supplementary capabilities. This
profile does not increase the ceilings to compensate for missing sources.
SDK retries are disabled; each actual model request acquires one process-wide
model slot. Specialists/challenge use quick, synthesis uses deep.

Native checkpoints persist independently of the classic checkpoint toggle.
Active execution defaults to 300 seconds, excluding queue time. Interrupted
runs can use `POST /api/runs/{id}/resume` after identity and integrity checks.
Profile, mode, source policy, question, cutoff, holding context, configuration
and workflow version must match. The exact saved V0 and validated stage results
are reused. A validated SDK response saved before the kernel's MAIN result can
also be recovered without a new request. Unknown dispatched calls remain spent
and are not automatically redispatched; missing token usage stays unknown.

Cancellation and publication authorization share the manager's lifecycle
lock. Cancellation first prevents publication; authorization first preserves
the candidate's right to publish and rejects late cancellation. Native record
publication is mandatory: a publication failure cannot produce `run.completed`
or a fallback classic/catalyst case. Recovery verifies the saved candidate,
authorization barrier and public bytes. Reports are derived from that same
record, without a second summary model.

## Read a result

`GET /api/runs/{id}/reader/record` reads the committed `research-record-v1`.
Native records require their assessment and no paired legacy case. The
workbench routes an explicitly native run to this record as its single main
Reader. It shows the judgement, up to three key claims, primary risk and next
check first; historical quantitative context remains on the main surface.
Supporting facts and saved original content are available on demand. Missing
publication stays unavailable rather than showing a legacy summary.

`ready` means readable, and `completed` means the execution/publication path
finished. Neither establishes complete research or predictive accuracy. Inspect
the assessment's completeness, quality, per-dimension limitations and unresolved
challenges separately. `partial / LOW_CONFIDENCE` remains visibly limited
research. Source/model failures and budget refusal do not become verified facts.

Reader, audit, SSE replay/reconnect and report reads make no model or provider
calls. Markdown is stored in the run's `reports/complete_report.md` in the local
durable store. This engineering integration has no paid quality comparison or
real-world predictive-accuracy acceptance; default migration remains separate.
See [the shared record contract](../contracts/research-record.md) and
[architecture](../../ARCHITECTURE.md) for canonical ownership.
