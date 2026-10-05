# Web unified evidence research

Status: Implemented and functionally verified locally — option A, Web-only; human reading and comparative quality acceptance remain open.

This document records scope and rationale. Code and the acceptance review establish current behavior.

## Goal and scope

Make the Web workbench a usable single evidence-driven product. New single and
batch runs use `evidence_v1`; no classic/catalyst profile chooser, analyst preset,
debate depth or classic horizon controls remain in creation. Company research is
the default; an explicit research scope supports catalyst research and holding
review with real user-declared holding context. CLI analysis is outside this work:
do not migrate it. The existing Web launch command stays available.

Legacy records remain readable and interrupted runs recover with their saved
profile, workflow, inputs and spent budgets. No history, local configuration or
user data is rewritten. Web creation explicitly requesting a retired profile is
rejected with a stable error; legacy retry must not create another legacy run.
Users can instead start a fresh native research request. Native retry is retained.
The creation-disable switch blocks single creation, batch creation and native
retry; saved reads and identity-validated resume remain available.

## Contract and creation boundary

Change the Web request default to `evidence_v1`, independently of the neutral
AnalysisRequest and legacy deserialization defaults. Native creation is enabled
by default, with an explicit environment disable still respected. Config reports
the creation support and native defaults. Both batch item configuration and run
requests carry native mode, question and profile; batch remains company-only,
1–8 distinct companies, existing FIFO/concurrency/cancellation semantics.
Reject unsupported markets before enqueue or network work. Native request
builders send canonical compatibility scheduling defaults, never hidden classic
form selections. Model selection and existing effort/config inheritance remain.

## Evidence and valuation

Use the existing bounded collector and qualification pipeline. Add a new workflow
version for changed source topology; prior workflow versions retain their original
collectors, record construction, specialist fact views, dimension gates, kernel
context and prompts on recovery. Both v3 and the new v4 retain scoped coverage;
v3 must not gain v4 valuation routing or revised mode dimensions. New valuation collection uses inspectable direct
HTTP candidates behind BudgetedSession and the durable source journal. Admit only
exact security identity, CNY units, explicit observation/report dates at cutoff,
finite valid arithmetic and saved source content/hash. Provider errors, stale
quotes, ambiguous units and unverified historical vintage stay unavailable.

Compute price/multiple context and any reference anchors deterministically from
qualified frozen inputs. Reuse existing valuation arithmetic where its inputs can
be populated without guessing. A missing historical/peer anchor remains explicit;
a current multiple alone cannot manufacture a fair-value interval. Models receive
read-only valuation facts through the appropriate specialist input, with the
valuation dimension ceiling based on admitted inputs rather than a hardcoded
absence. Optional additive saved valuation context preserves old record bytes.
The minimum valuation output is qualified Tencent price, PE-TTM, PB and market
capitalization at the last proven settled session. This permits conditional
multiple/positioning discussion only. Tushare daily_basic can provide a bounded
current-capture history; disclosed annual parent-company net income plus matching
market-cap/share arithmetic can populate the existing reference-anchor chain.
Missing history or annual base produces explicit unavailable anchors. Save the
deterministic assessment and input evidence IDs/hash in an optional `valuation`
field of research-record-v1; validate run/ticker/cutoff and admitted references.
Valuation facts go to operating_quality; new company/holding dimensions admit
only valuation-family facts. No snapshot/history alone proves intrinsic value.

For 600803, verify the Shanghai calendar/adjusted-price route. Use existing Tushare
calendar if qualified; add a public fallback only when its exchange and complete
settled-session contract can be proven. Never borrow Shenzhen sessions or relax
PIT to make a run appear complete. Keep existing model/data/HTTP hard ceilings.

## Reader

One main report: identity/cutoff/scope → conditional judgement → principal risk
and blocking unknowns → up to three grounds → code-computed valuation/risk context
→ next check → expandable hypotheses/verification/coverage/process. Severe limits
remain visible. Source references open saved content before metadata with keyboard
focus, Escape and return-focus support. No expansion, refresh or report read
dispatches data/model work. Markdown/JSON/Reader share one committed native record.
An available current multiple is labelled as positioning, never as intrinsic
value. Render unavailable values and reasons rather than invented numeric ranges.

## Verification and completion

Check Web single/batch default routing, retired-profile/retry rejection, native
mode/holding validation, historical read/resume, cutoff/identity/source failures,
valuation math and lineage, frozen replay and budgets. Run scoped Python suites,
Vitest, typecheck/build (including tracked static), docs/Ruff/diff checks and
current Playwright scenarios. Reconcile stale tests against canonical contracts;
retain valid failure assertions and distinguish environment failures.

Real paid smoke uses only 600803, configured DeepSeek, existing bounded stages
and an isolated temporary run store, at most two fresh runs (24 model attempts
total) for implementation repair; no automatic fresh-run loop. First run company research; reuse frozen
evidence for additional checks where possible. Test batch/modes/failure states
offline without fabricated live holdings. Inspect actual saved evidence and
arithmetic, costs/attempts, readable partial states, reconnect and zero-dispatch
reads. Show the actual report in the browser at desktop, 390px and a narrow viewport equivalent to 200% zoom,
with screenshots and an HTML result preview. User reading acceptance remains a
human check; one live symbol cannot establish comparative predictive accuracy.
Do not execute the old multi-case paid evaluation budget or publish remotely.
Update README, README.zh-CN, ARCHITECTURE, docs/README, evidence-research and the
shared record/valuation contracts as applicable to the final implementation.

On 2026-10-04 the user explicitly approved one additional validation run after
the two fresh runs used 10 SDK attempts. This additional run reuses the first
run's frozen, qualified evidence, performs no new source requests, preserves
both original runs, and has a stricter six-SDK-attempt ceiling. It validates the
repaired model pipeline; it does not prove live provider availability or
comparative research accuracy.

The [dated acceptance review](../../reviews/2026-10-04-web-final-acceptance.md)
records the completed local checks, all three real trials and their remaining
research-quality limitations.
