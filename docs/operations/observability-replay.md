# Observability, recovery and offline tools

Status: Current

This reference covers durable execution evidence and troubleshooting, not investment-quality scores.
Use [Web operations](evidence-research.md) for user actions and the
[research contract](../contracts/research-record.md) for publication/budget semantics.

## Events and recovery

`events.jsonl` is an append-only, versioned lifecycle stream. `RunStore` assigns a monotonic sequence
under a per-run RLock and fsyncs events; `EventBroker` persists before publishing. Subscriber setup
captures the disk watermark before joining live delivery. Slow queues close; reconnect replays from
the cursor, not by rerunning research. `after` and `Last-Event-ID` must agree when both are supplied.

The locks and sequence cache belong to one store instance. The supported Web launcher acquires a
cross-process owner lock before startup recovery and holds it until shutdown; a second launcher
using the same directory fails even on another port. Directly constructed stores still require a
single writer. If an event is durable but its snapshot write was interrupted, reopening replays the
missing events to restore status and completion fields. These bounded fixes do not establish
universal crash consistency; see the [review](../reviews/2026-10-25-documentation-code-audit.md).

Native/catalyst checkpoints persist attempt transitions, frozen inputs, hashes and qualified outputs
independently of the classic checkpoint toggle. Resume validates the saved identity and reuses saved
results; uncertain dispatched work stays consumed. No recovery may reset pools or upgrade old prompts.
Keep reports, caches, run records and checkpoints as user data; no routine cleanup is implied.

## Diagnostics and privacy

Safe public diagnostics use fixed categories/codes, permitted field paths, HTTP status and measured
counts. They exclude arbitrary exception messages, rejected responses, credentials and model reasoning.
Native diagnostics distinguish request/configuration, JSON/schema, reference qualification and report
publication failures. Unknown historical failures are not reconstructed from prose.
Numeric failures may name a declared text field, without retaining its full model-supplied path.
Schema length failures may include declared envelope fields and numeric limits/actual counts;
unknown names remain redacted and arbitrary validation context is never copied.
`inline_binding_shape` identifies an invalid model-facing inline envelope using a fixed code;
it never exposes the rejected payload or a model-supplied address.

`scratchpad.jsonl` keeps bounded lifecycle markers and stable hashes/artifact references;
`cycle-record/<sha256>.json` links a cycle's safe spec/query, event span and report references.
Neither is a store for private reasoning, raw tool arguments or raw provider results. Canonical owners
are [observability](../../tradingagents/observability/) and [runtime](../../tradingagents/runtime/).

For an explicitly authorized synthesis investigation, `TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES=1`
captures rejected final synthesis text into ignored `output/v8-synthesis-debug/<run_id>/` with hashes
and owner-only access. Default is off; no reasoning/config/exception text is included, and capture
failure cannot change research. It is local debug material, not a public artifact or ordinary logging.

## Retry and accounting

Versioned native retry policy permits up to three transient retries for one call, with 2/5/10-second
waits. Baseline calls share three retries across the run and the baseline attempt ceiling;
the active deadline still applies. SDK retries remain disabled.
Known permission/quota/configuration failures and incomplete streams are not transient retries;
structurally invalid completed output uses the separate bounded repair path. Focus has no retries.
V8 supplementary reviews charge their retries/repairs to the separate review pool and its per-round
ceiling; historical workflows retain their original budgets.

Reservations, SDK authorizations, actual network delivery, provider success and billing are different
facts. Missing token counts stay unknown, never zero. Each saved SDK request's measured usage is
counted once, including failed requests. Counts may be complete, lower-bound or unrecorded in older
histories; adding observation during recovery cannot certify prior calls.

## Saved-run measurement tools

Run from the existing contributor environment against saved runs or copied fixtures. These tools do
not start a manager, make model/provider calls, repair snapshots or write run data. Output is stdout;
redirect outside the run directory if needed.

| Tool | Purpose and supported boundary |
| --- | --- |
| [eval_benchmark.py](../../scripts/eval_benchmark.py) | Saved committed V1/V2 delivery/stance, attempts, measured usage and challenge counts, parsed through the versioned codec. Supports V8 records; workflow filters define comparison cohorts. |
| [replay_synthesis_input.py](../../scripts/replay_synthesis_input.py) | Reconstruct a V7 synthesis context in memory, validate cached predecessors and compare saved input hashes; stop before model dispatch. |
| [profile_native_inputs.py](../../scripts/profile_native_inputs.py) | Verify V7 context and actual rendered main/repair prompt hashes, then measure bytes/characters and optional scope inventory. |
| [compare_native_prompt_views.py](../../scripts/compare_native_prompt_views.py) | Compare an offline reversible metadata codec, including all prompt overhead and no-op cases; production prompts/identities remain unchanged. |

```bash
python scripts/eval_benchmark.py --format json
python -m scripts.replay_synthesis_input --run-id RUN_ID
python -m scripts.profile_native_inputs --run-id RUN_ID --include-inventory
python -m scripts.compare_native_prompt_views --run-id RUN_ID
```

Select artifacts through committed events and hashes, never file modification order. These diagnostics
do not replace Reader publication eligibility. Unsupported reconstruction remains unavailable;
retain missing/corrupt/failed runs in cohort accounting instead of silently improving denominators.

Synthesis delivery, complete sections and formed stance are different measurements. Elapsed
creation-to-completion includes queue time. Token subtotals with missing usage are not true totals
or prices; hypothesis fact ratio is not semantic quality. Unknown annotated challenge coverage,
derived-metric coverage and manual scores remain null rather than guessed.

`native-input-inventory-v1` conservatively retains supplied entities with their scope, value/prose,
period/unit/source/limits and hash. Full restoration/retained ratio 1 proves structural preservation,
not that every economic input was supplied or that models reason equally well. Bytes are not token
estimates. The reversible candidate is measured with schema, markers and guidance included; positive
byte savings do not authorize production compression or establish real token/cost savings.

## Quality evaluation

Manual `hypothesis-quality-v1` evaluates specificity, falsifiability, decision relevance and information
beyond restatement, with run/entity IDs, scorer, per-axis reasons and rubric version. Empty hypotheses
are unscored, not zero. Changing scorer or criteria prevents unqualified comparison with earlier
scores. The original V8 *reasoning roadmap* is separate from the shipped V8 search-workflow identity.

| Axis | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Specificity | Generic description | Company-specific relationship | Relationship, comparable period and scope with qualified support |
| Falsifiability | No observable disconfirmation | Observable contrary evidence | Executable check or precise future observation bound to a judgement-changing condition |
| Decision relevance | No link to judgement | Relevant operating/valuation/event/market implication | Explains how confirmation/refutation changes stance or a material dimension |
| Beyond restatement | Repeats a field/title/disclaimer | Supported interpretation plus alternative | Distinguishes explanations with evidence or a discriminating test |

Use 2/4 only between anchors. Average four axes per hypothesis, then saved hypotheses per run.
The historical proposal names Claude as scorer; identify a replacement before comparing subjective
scores. Do not reward optimism, fluency, caveat count or schema success. No scoring call is implied.

Offline fixtures and hash equality establish only their tested properties. Source coverage, real
model compliance/cost/latency, human comprehension and economic/predictive quality need separately
scoped acceptance. Original evaluation protocols and historical measurements remain in the
[archive](../archive/README.md); they are evidence records, not current runtime instructions.

<!-- Compatibility anchors for existing section links. -->
<a id="v7-reply-observations"></a>
<a id="事件写入与-sse-恢复"></a>
<a id="原生模型失败诊断"></a>
<a id="原生模型有限网络重试"></a>
<a id="可回放运行记录安全边界"></a>
<a id="安全规则"></a>
<a id="当前范围"></a>
