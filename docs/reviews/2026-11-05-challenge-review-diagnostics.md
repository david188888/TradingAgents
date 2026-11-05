# Challenge review diagnostics — live run 2026-11-05

Status: Dated diagnosis record. Not current-state architecture or operating guidance.

Phase 4 of [the capability-catalog plan](../plans/2026-11-05-capability-catalog-controlled-supplement-plan.md):
diagnose why the challenge stage kept failing with unreviewed targets, after adding
`insight.diagnostics.challenge`, a prompt constraint and one bounded review repair (PR #49, #50).

## Run

| Item | Value |
| --- | --- |
| Run | `run_20261105T123620116834Z_533734b4` (workspace-local store, user run stores untouched) |
| Ticker / date / model | `002130.SZ` / 2026-11-05 / DeepSeek `deepseek-flash` both tiers, thinking high |
| Result | `completed` in 614 s, readable report, synthesis stance 中性 over 13 accepted Insights |
| Challenge tokens | main 123,921 in / 9,181 out; repair 124,013 in / 3,800 out |

## What the diagnostics show

13 accepted Insights were reviewed; the model returned 13 reviews in the first pass.

| Observation | Value |
| --- | --- |
| First-pass reviews accepted | 12 of 13 (11 challenged, 1 no-counterevidence) |
| First-pass rejections | 3 targets (`I4`, `I8`, `I12`) — all `numeric_literal_unbound` |
| Bounded repair | 1 call; repaired `I8` and `I12` |
| Remaining | `I4` still `numeric_literal_unbound` → `repair_unresolved`, 1/13 unreviewed |
| Stage result | `failed` only because of that single unreviewed target |

Journal entries: `insight.diagnostics.challenge` = 4 × `numeric_literal_unbound` (three first-pass
targets plus the failed repair) + 1 × `repair_unresolved`.

## Root cause

The review text must pass the same numeric-binding rule as Insights: any Arabic numeral in
`concern`/`reasoning` needs a host-rendered `[N]` token. Reviews that quoted dates or amounts
digitally (e.g. `11月5日`) were therefore discarded as a whole. Chinese-numeral or qualitative
phrasings in the other reviews passed, which explains the partial success. The bounded repair works
(2 of 3 repaired); the residual failure is this specific number style.

## Targeted fix (offline)

1. The repair context now carries an explicit instruction when any issue is
   `numeric_literal_unbound`/`numeric_scope`: rewrite only the listed targets, remove every Arabic
   digit from concern/reasoning (use Chinese words or the saved `[N]` token), cite only saved E refs.
2. The challenge task prompt now says the same: no Arabic digits in concern/reasoning (dates and
   amounts in Chinese words, or the saved `[N]` token).

## Remaining

One more authorized live run is needed to confirm the challenge stage completes. The prior failure
modes improved from 4 of 7 discarded, to 9 of 9, to 1 of 13 with repair; this fix targets the last
observed reason code.
