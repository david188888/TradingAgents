# Saved evidence benchmark

Status: Current

`scripts/eval_benchmark.py` is a read-only measurement tool for the V8 plan's
Phase 0 baseline. It uses standard-library artifact readers and project canonical
models for typed challenge validation, and never constructs a
run manager, calls a model/provider, repairs a snapshot, or writes run data.

```bash
python scripts/eval_benchmark.py --workflow evidence-production-v7
python scripts/eval_benchmark.py --workflow evidence-production-v7 --format json
python scripts/eval_benchmark.py --runs-root /path/to/copied/runs --run-id RUN_ID
```

Output goes to stdout. Save it outside the run directory using shell redirection
when a durable report is needed. There is no automatic benchmark execution.
The default source is `~/.tradingagents/web/runs/`; missing directories are
reported without creating them. Corrupt runs are reported separately and make
the command exit nonzero, rather than silently improving the denominator.

## Measurement boundaries

- Artifacts come from committed events, with SHA-256 verification, never from
  filenames sorted by modification time. Detached artifacts are ignored.
- Artifact integrity is checked, not full publication authorization or domain
  validity. This tool does not replace the canonical Reader validators.
- Synthesis success requires an actual synthesis attempt and a committed record
  with `synthesized` or `analysis_unrated`. Older records lacking `report_status`
  require the accepted `native.synthesis` cache as well as a committed record.
  A pre-synthesis failure has a null synthesis result and stays visible in the
  cohort run count. Stance formation is a separate metric. This measures usable
  synthesis delivery, not completion of all sections. For sectioned reports,
  accepted/unavailable counts and `synthesis_sections_complete` identify pending
  work independently. Historical records without section metadata stay null.
- Attempts count dispatched main/repair/retry/focus/preprocessing ledger entries.
  Reserved-only entries and data calls are excluded. Repair/retry ratio uses
  actual dispatched attempts, including failures, as its denominator.
- Token subtotals use `native.model_usage` once per saved SDK request. These
  entries include measured failed responses that can be absent from ledger
  token fields. Missing usage is unknown, never zero; `usage_complete` requires
  matching ledger request identities and both token counts. Synthesis token
  share is a share of the measured subtotal, not necessarily the true total.
- Hypothesis fact ratio is unique supporting fact IDs divided by all saved fact
  IDs. Saved metric count is separate from derived-metric coverage; the latter
  stays null until a versioned formula catalog supplies an auditable definition.
- Executed verification count excludes unavailable verification records. Fixed
  local evidence checks are counted separately and cannot be mistaken for
  hypothesis-directed checks. This count does not mean an economic question
  has been resolved.
- Elapsed seconds run from creation to completion and include queue time. They
  are not active execution latency. Missing completion remains null.
- Cohorts separate workflow, provider, specialist model and synthesis model.
  Small historical samples and mixed policies cannot establish forecast quality.

`hypothesis_directed_checks` reports versioned classification completeness,
task/execution counts, successful predicate results, unavailable reasons and reply
dispositions. Old records report these as not recorded. Frozen annotated coverage
and correct task-generation rates are computed by `research/challenge_metrics.py`;
the CLI does not supply annotations and leaves those rates null. Its legacy
`challenge_test_request_ratio` and manual rubric fields also remain null.
The script never guesses executability from prose.

For exact stage input sizes and a conservative preservation inventory, use the
[native input profiler](native-input-measurement.md). It separately verifies
canonical context hashes and rendered prompt hashes, and keeps byte counts distinct
from SDK token usage. Its input inventory does not select or compress evidence.

## Offline synthesis reconstruction

```bash
python -m scripts.replay_synthesis_input --run-id RUN_ID
```

This standalone V7 diagnostic reads the latest committed checkpoint and clones
it in memory. It bypasses the terminal output cache only in that copy, validates
upstream cached proposals and numeric receipts through the existing kernel, and
stops before synthesis dispatch. It prints only saved/reconstructed hashes and
their equality. A missing uncached stage is blocked; it never obtains a new
model response, constructs a run store, or persists a frontier. A mismatch or
unavailable reconstruction exits nonzero. Matching input hashes establish exact
reconstruction, not the correctness of a failed response that was never saved.

## Manual hypothesis rubric: `hypothesis-quality-v1`

Score each saved hypothesis from 1 to 5 on each axis. Use the saved statement,
its facts, conditions, tests and responses; quote the exact relevant IDs in the
review. Score 2 or 4 only when the record falls between adjacent anchors.

| Axis | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Specificity | Generic company/risk description | Identifies a company-specific relationship | Identifies the relationship, comparable period and applicable scope with qualified support |
| Falsifiability | No observable disconfirmation | States observable contrary evidence | Binds an executable check or a precise future observation to the condition that changes the hypothesis |
| Decision relevance | No connection to investment judgement | Explains a relevant operating/valuation/event/market implication | Explains how confirming or refuting the hypothesis changes stance or a material judgement dimension |
| Information beyond restatement | Repeats a field, title or disclaimer | Interprets a supported relationship and names an alternative | Distinguishes competing explanations with evidence or a discriminating test |

A hypothesis score is the mean of its four axes; a run score is the mean over
all saved hypotheses. A run with no hypotheses is unscored, never assigned zero.
Record rubric version, scorer, run IDs, evidence references, axis scores and
short reasons. Compare versions on the same benchmark companies and model.
Do not reward an optimistic stance, fluent wording, numerous caveats or a passed
schema. No additional model call is authorized or triggered by scoring.

The V8 proposal names Claude as the manual scorer; the identity of a replacement
scorer must be stated explicitly before treating new subjective scores as
comparable. Deterministic baseline counts require no such scoring decision.

See the [V8 proposal](../plans/2026-10-17-evidence-reasoning-architecture-v8.md)
for staged targets; those targets are not current product guarantees.
