# Factual premises

Status: Current. This policy separates source observations, bounded comparisons,
interpretations and pending questions. It does not prove free-prose entailment.

V7 and V8 research freezes `factual-premises-v1` alongside `anchored-narrative-v1`.
The canonical types are in
[`_factual_premise.py`](../../tradingagents/agents/schemas/_factual_premise.py)
and [`_numeric_stage.py`](../../tradingagents/agents/schemas/_numeric_stage.py).
[`factual_premises.py`](../../tradingagents/research/factual_premises.py) owns
compilation and public projection; the existing numeric receipts own replay.

V8 extends this baseline through the [dual-search contract](dual-search-research.md):
its V2 record binds recovered field qualification to its first snapshot, preserves
historical checks/receipts, and excludes stale arithmetic from current inputs.

## Observation ownership

The host builds source observations from qualified saved facts verbatim, retaining
source limits. Conflicting materials remain readable as attributed source statements;
they do not supply unqualified comparisons. Comparison and sign observations use
existing qualified numeric anchors. Financial directions reuse official comparable
FY/H1 differences or passed structured financial comparisons; no cross-supplier
cell assembly, arbitrary-period comparison or model arithmetic is introduced.
A difference on a negative base is a value comparison, not a growth percentage or
proof of economic improvement. Unknown metrics cannot become observations.

Each narrative binding selects observation IDs within its field's existing fact
scope. Specialist statements, maintained/revised replies, supported dimensions,
arguments and rated overall judgements require observations. Overall observations
must be covered by `key_claim_ids`. Unresolved text without observations is labelled
as an open question. Interpretations carry an explicit host label and may declare
qualitative pending questions. These questions are never compiled as observations.

## Workflow and delivery

The model envelope adds per-field `premises`; the compiled field receipt adds a
`premise` with the selected host observations and pending questions. Missing or
unknown bindings, out-of-scope observations and missing required support have closed
`premise_*` error codes. Existing bounded repairs, specialist sibling isolation and
sectioned synthesis continue to apply. No additional model call or retry allowance
is introduced. The existing overall/critical publication gates remain authoritative.

Reader professional text, related-evidence views and Agent stage details use the
same accepted receipt. Markdown includes a trace appendix of accepted process fields;
a saved interpretation can subsequently be revised or withdrawn, so the appendix
is not a new set of final supporting arguments. Beginner explanations receive the
same premise context, and pending questions remain visible beside the explanation.
No interpretation is labelled as semantically verified.

## Compatibility and validation

Old identities retain their original envelopes, text, serialization and replay.
Absent optional receipt fields are omitted on serialization. New identities cannot
silently use old envelopes. Stage reading reconstructs the observation catalog from
saved qualified inputs before exposing the binding. Publication replays the compiler
and compares the public catalog and field receipts. No historical record is rewritten.
Final Agent reading also requires the frozen premise policy to match the saved kernel
input and output identity. Unknown or mismatched identities expose neither the Agent
proposal nor its premise text; qualified unpublished stages retain their own receipt gate.

Offline validation covers structure, calculation, scope, isolation, stage reading,
publication, rendering and historical compatibility. A deliberate negative semantic
case is also retained: a valid revenue observation plus an unsupported sales-expense
assertion in free interpretation can still pass structural validation. That is a
known semantic false negative, not successful detection. Arbitrary prose entailment,
source truth, causal interpretation and predictive quality remain outside this gate.
Actual model compliance, token costs and reasoning quality require separately
authorized live evaluation; passing offline tests is not such evidence.
