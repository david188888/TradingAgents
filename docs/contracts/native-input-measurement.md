# Native input measurement and preservation inventory

Status: Current

`scripts/profile_native_inputs.py` is a standalone, read-only V7 diagnostic.
It shares the private reconstruction in `scripts/replay_synthesis_input.py`;
`scripts/native_input_inventory.py` owns deterministic sizes and preservation units.
It does not change production prompts, evidence selection, budgets or recovery identity.

```bash
python -m scripts.profile_native_inputs --run-id RUN_ID
python -m scripts.profile_native_inputs --runs-root /path/to/copied/runs \
  --run-id RUN_ID --include-inventory
```

JSON goes to stdout. Save it outside the user run directory. Default output contains
hashes, IDs, counts and sizes; `--include-inventory` adds scope paths and content
hashes, not source text or prompts. Provider credentials are not exported.

## Reconstruction and integrity

The reader selects the latest committed checkpoint from the complete event log,
checks its artifact hash and run identity, then clones it in memory. The real
kernel supplies specialist, challenge, targeted-response and synthesis contexts.
Cached predecessors retain their canonical validation; uncached model work and
verification dispatch are blocked. No RunStore, SDK client, network operation,
data collector or persistent journal is constructed for profiling.

The canonical context must match its saved `native.<stage>.input` hash. Prompt
rendering uses the existing adapter in memory, with the saved config, alias/schema
versions and repair diagnostics. Main and repair prompts must each match their
saved SHA-256 before any reconstructed model-context sizes are reported as actual.
A mismatch remains explicit and has no candidate size presented as an actual size.
The prompt is decoded structurally, so marker strings inside source JSON do not
split it into false sections.

Successful reconstruction is not a publication authorization or economic-quality
check. This command is a separate process, never an in-process Web service component:
reconstruction temporarily patches process-local kernel/verification entry points.

## Measurement units and unknowns

- Canonical kernel context and actual model context are separate. Numeric validation
  receipts intentionally omit some source/task fields and are not full prompts.
- Characters and UTF-8 bytes are exact for the reconstructed serialized payload.
  Prompt prefix, schema, context and trailing guidance form disjoint spans; JSON
  component sizes retain container syntax separately. They are not token estimates.
- Repetition counts identical complete string values of at least 64 UTF-8 bytes.
  It excludes repeated keys and substring similarity. Repeated payload bytes are
  neither proof of redundant meaning nor removable savings.
- Dispatched ledger entries, SDK dispatch markers and saved SDK usage are separate.
  A custom caller can dispatch a ledger authorization without an SDK request.
  A saved repair prompt can exist without a dispatched repair. Neither proves
  network delivery, billed tokens or monetary cost.
- Each saved usage key is counted once. Dispatched attempts without measured input
  or output retain null and increase the corresponding unknown count. Usage without
  a matching dispatched ledger entry is reported separately, never discarded.
  Failed/retried requests remain present; reserved-only entries are excluded.
- Baseline reconstruction ends before synthesis dispatch. Supplementary focus or
  other requests not reconstructed remain visible in usage rows with unavailable
  context. Post-completion plain-language explanation jobs are outside this ledger.
- Exit 0 requires every dispatched ledger attempt's prompt to be hash verified;
  this does not mean token usage is complete. Exit 1 reports incomplete prompt
  coverage; exit 2 is an explicit read/reconstruction failure. An unreconstructable
  run must remain an unavailable sample in any downstream cohort, not be dropped.

## Conservative preservation contract

`native-input-inventory-v1` records **all supplied schema and model-context content**
as a conservative floor for a later candidate view. It is not a proven minimal
evidence set or a claim that all economically relevant facts were supplied.
`inventory()` and `compare_inventory()` are pure helpers and are not production gates.

| Task | Content that the initial checklist retains |
| --- | --- |
| Specialist | Allowed facts and their evidence bindings; supplied source text, dates, qualification and limits; metrics, numeric periods/units/precision/lineage; factual observations; role scope and company background |
| Challenge | Supplied facts and original hypotheses/conditions; classifications and capability domain; independent check inputs; local checks, limitations, conflicts and counterevidence; allowed IDs and observation bindings |
| Targeted response | Assigned challenge/hypothesis pairs; allowed facts per challenge; their sources and limits; saved propositions, outcomes and verification scope; reply/reference restrictions |
| Synthesis | Dimension-allowed claims, arguments and replies; all supplied challenges/outcomes; counterevidence and gaps; numeric and factual bindings; source provenance, company context, ceilings and section requirements |
| Repair | The exact requested schema/context for that repair, including narrowed synthesis sections where applicable; parent task requirements remain separate and are not replaced by repair-only coverage |

Entities are atomic: their ID, prose/value, period, unit, source and limits remain
bound by one content hash. Scope paths stay distinct; a fact preserved only inside
an unrelated receipt cannot replace an allowed task fact. Exact duplicate entities
within the same scope share one requirement. Scalar/reference lists retain order.
Deletion, rounding, period changes, missing conflict limits and reference/scope
changes appear as missing units. Schema/reference choices are also inventoried.

A retained ratio of 1 proves only this conservative content/scope comparison.
It does not prove entailment, causality, reasoning quality or semantic completeness.
Any future proposal to drop or transform a unit needs an explicitly justified
preservation rule plus the existing canonical numeric/F02/reference validators
and counterexamples. Inventory coverage cannot replace those gates or F07 review.

## Offline reversible metadata comparison

`execution/native_prompt_view.py` owns the offline `lossless-numeric-metadata-v1`
codec. It stores complete metadata once in the existing `numeric_meta` and an
ordered alias list in `numeric_catalog.metadata_aliases`. All other model-context
content is copied unchanged. It is not called by the production prompt builder,
kernel, Reader or recovery path; no new runtime identity is enabled.

`encode_context()` validates the existing canonical numeric catalog schema in
strict JSON mode, the known numeric policy and both alias mappings. Metadata
copies must have identical compact sorted JSON, including types and bindings.
`decode_context()` accepts only the closed protocol and exact contiguous alias
list; object insertion order is immaterial, array order is retained. It never
resolves files, URLs or generic references. `verify_roundtrip()` requires the
decoded complete JSON to equal the original. A standalone decoder validates
structure, not historical authenticity; a structurally valid text substitution
can only be identified with the original comparison.

Valid empty metadata and contexts with all numeric components absent produce
explicit no-ops. Partial components, null/unknown policy, schema violations,
alias conflicts and failed reconstruction are errors, never a silent fallback.
The codec creates nonempty candidates regardless of their size; it cannot decide
the benefit of a complete prompt.

```bash
python -m scripts.compare_native_prompt_views --run-id RUN_ID
python -m scripts.compare_native_prompt_views --runs-root /path/to/copied/runs \
  --run-id RUN_ID
```

This standalone script reuses the private reconstruction above. It verifies
original kernel and saved prompt hashes before comparing each main or repair,
including narrowed synthesis repairs. Context replacement uses structured JSON
spans. It retains the original schema, prefix and trailing guidance and counts
the new marker, alias list, newline and protocol guidance in full UTF-8 bytes.
Only positive net savings select `packed`; otherwise the effective prompt and
hash are unchanged. Candidate and effective sizes are reported separately.
Inventories are compared against the **decoded** candidate, after full equality;
the packed paths are not treated as the original inventory.

The versioned JSON report contains hashes, decisions, counts and sizes, never
prompt/source text or config credentials. `all_prompt_samples` includes saved
prompts and failure placeholders for expected/missing contexts. Ledger totals
weight each corresponding phase by its dispatched attempts, including retries;
saved-but-undispatched repairs remain separate. Failed samples stay in counts,
and byte totals explicitly describe only compared samples. Unknown usage and
unmatched saved usage remain visible; candidate SDK tokens always remain null.

Exit 0 means the offline comparison is complete, including legitimate no-ops;
it is not a claim of token completeness or quality. Exit 1 means a missing,
mismatched or failed prompt comparison. Exit 2 emits a failed-run JSON record
for read/reconstruction failure. Retain that record in any cohort.

No models, providers, stores, migrations or service restarts are performed.
Exact data restoration does not establish model compliance, equal reasoning
quality or actual token savings. Production integration requires a separate
policy/identity and model-effect validation decision; all budgets remain unchanged.
