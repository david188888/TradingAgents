# Hypothesis-directed challenge checks

Status: Current

Fresh V7 runs freeze `challenge_check_policy=hypothesis-directed-checks-v1`.
It selects challenge V3 proposals and `verification-plan-v2`. Absence preserves
historical proposals, original-condition tasks and resume behavior. Additive
fields are omitted from old `research-record-v1` serialization and hashes.

## Ownership and evidence scope

`agents/schemas/_challenge_verification.py` owns classification, typed input
requirements and code-owned task outcomes. `_native_stage.py` owns V3 proposals
and bounded acceptance records. `research/challenge_checks.py` validates frozen
inputs and assembles independent proposition tasks. `_verification_plan.py` owns
their plan; `execution/verification_executor.py` dispatches on the existing
durable budget and recovery frontier.

Every material/critical challenge needs a classification. It may propose an
independent check absent from its target hypothesis's original conditions.
Additional supporting facts must belong to qualified V0 evidence; the original
hypothesis, assumptions and falsifiers remain unchanged. A selected original
condition is background, never an implicit replacement check.

Challenge prose can cite its target's facts and its explicitly selected facts.
Its calculation must use evidence covered by the latter bindings. Replies see
their specialist partition, assigned challenge facts and corresponding checks,
without unrelated drafts. Numeric operands, metrics, predicates and observation
dates retain receipts; predicate plans bind to the challenge's `proposed_test`.
F02 observations follow the same expanded challenge scope.

## Classification and execution

- `computable_now` requires qualified saved inputs and an executable check.
  Financial comparisons use one field, matching earlier periods and one evidence
  ID. A shared source family alone is insufficient; existing numeric frequency
  and unit qualification still applies.
- `computable_unsupported` requires typed inputs and a field, metric, operation
  or formula-domain gap. Raw fields do not establish a cross-field formula.
  Zero/negative growth bases are `input_domain_unsupported`; code never invents
  a replacement growth formula.
- `needs_source` requires missing/unqualified supported inputs, or a prose-source
  requirement whose availability code cannot determine. The latter remains
  model-proposed `availability_unknown`, separate from confirmed missing inputs.
  Financial periods after the cutoff cannot be hidden in this category.
- `future_observation` requires an observation date strictly after the analysis
  date and has no executable check.
- `not_testable` carries a closed reason: no observable counterevidence or an
  undefined measurement. It remains a model classification.

Code checks structural and data consistency, not natural-language entailment,
causality or completeness of declared inputs. Minor challenges may omit
classification and do not enter important-challenge rate denominators. The
limit remains three tasks in one supplementary round; no extra retrieval,
derived formula or model allowance is introduced.

Per-item schema, reference and numeric failures use the existing single repair
opportunity within the shared run budget. A valid whole repair replaces the
main proposal; otherwise valid main siblings retain their original indices and
numeric/F02 receipts. Rejected prose is discarded; index and closed reason are
retained. All rejected differs from a valid zero-challenge proposal.

Each accepted challenge saves its task outcome: not generated with its
classification, completed, budget refused, cancelled, or unknown dispatch.
Only completed tasks have execution records/timestamps. Tool failure is executed
but unavailable. Results carry exact values, `predicate_met`, hashes and lineage;
`scope=challenge_predicate_only` means supports/contradicts refer only to this
proposition. They do not automatically close economic risks or change replies.

Saved results survive later cancellation. Unknown dispatch is not retried;
changed input or plan fails before dispatch. Public validators replay pure
arithmetic and bindings. Reader, related evidence, stage views and Markdown do
not dispatch tools, fetch sources, call models or write run data. Historical
missing classification is displayed as unknown.

## Measurement

`research/challenge_metrics.py` separates accepted-item classification
completeness from coverage over frozen annotated important cases. Omitted,
isolated and repair-deleted cases remain in the frozen denominator. Correct
task generation requires the expected target, proposition and check. Unknown
real-run annotations leave these coverage rates null.

Actual execution is completed important task count / generated important task
count; successful results are valid predicates / executed important task count.
Zero denominators are null/not applicable. Tool failures, unknown input
availability and reply dispositions are separate counts. Changed replies do
not establish better judgement. See the [benchmark contract](evidence-benchmark.md).
