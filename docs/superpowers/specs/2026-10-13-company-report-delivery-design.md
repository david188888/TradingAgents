# Company report delivery

Status: Approved design — implementation and offline validation are recorded in
the dated company-report-delivery validation review. Current contracts remain
authoritative for runtime behavior.

The user approved a basic company report with public company introduction,
fundamentals, quantitative context, events/risks, judgement and local unknowns.
Broker consensus is optional. If synthesis returns no usable content, publish
the saved basic report and valid specialist summary, explicitly mark synthesis
unfinished and do not invent an overall rating. No further live model calls.

## Ownership and compatibility

Fresh V7 identities freeze a new report-delivery policy separately from the
existing quote/cautious-judgement policy. Its collector admits an optional company
profile and its kernel uses the new report assembly. Identities without the
marker retain their exact prompts, fallback, ratings and serialized fields.
Unknown policy identities fail closed. Existing dirty changes and user runs stay.

The canonical public record gains an optional typed company-basics pack with
claim references for introduction, fundamentals and quantitative context, plus
local gaps. V3 assessment gains an optional report-status discriminator. Only
new-policy records may carry a null investment stance; it means no overall
rating was formed, never neutral. Old records omit all new unused fields.

## Foundation data

Keep Tencent price/market statistics and vendor financial statements independent
of PDF detail. Use the existing bounded Sina company page with security/exchange
verification to extract explicitly labelled company introduction, main business,
business scope and industry; do not infer one from another. Reuse qualified saved
disclosure excerpts as a profile fallback where an explicit business description
was admitted. Mark missing profile fields locally. Retain original source, dates,
numeric units and report periods. Broker forecasts, segment margins and detailed
PDF tables remain optional. Basic collection precedes specialist analysis.

All specialists receive a shared read-only introduction/foundation context, while
their hypothesis references and drafts remain role-scoped. They must not equate
their isolated view's missing fields with global missing data.

## Synthesis and report delivery

For the new policy, code owns copied invalidation text and reply pair/disposition
bindings. Model output selects known hypothesis/index pointers and writes actual
reasoning. The adapter restores exact saved text and bindings, then executes the
existing qualification and public-record validators; fabricated facts/references,
withdrawn support and unsupported favorable judgements remain rejected. Optional
copied metadata errors must not discard otherwise valid referenced reasoning.

Missing valuation/range/individual operating detail changes the relevant section
and permitted judgement strength. With qualified referenced reasons, a cautious
stance may be saved without every dimension being resolved. No automatic neutral
or favorable label is produced when reasoning is absent.

If synthesis is entirely invalid/unavailable, assemble section findings from the
actual qualified facts and effective saved specialist hypotheses; exclude revised
or withdrawn original assertions from active support. Preserve dialogue and code
checks. Mark report status specialist_summary and stance null. Do not attribute
host summary text to the synthesis model, claim a model adjudication occurred, or
hide cancellation/deadline/checkpoint failures. Those retain lifecycle semantics.

Report delivery and analytical coverage are separate. Unknown section questions
remain precise local limitations; a usable delivered report need not resolve
every analytical question. Reader and Markdown show company basics, retained
findings and the delivery state, rather than a blanket insufficient-evidence
verdict. Legacy records retain their historical label.

## Validation

Test labelled profile parsing, identity rejection, profile failure with financial/
market data retained, missing PDF/range/metric without output loss, host-owned
condition/reply binding, rejection of invented and withdrawn support, synthesis
failure with effective saved summaries and no rating, canonical publication and
Reader/Markdown provenance, old serialized hashes and checkpoint recovery.
Mock source/model transport and prohibit live model calls. Run scoped Python,
frontend unit/E2E tests, typecheck/build, Ruff, docs checks and diff checks; include
generated static assets. No Git publication, cleanup or Hindsight operations.
