# Plain-language report reading

Status: Current

The native Web Reader adds indicator definitions and saved model explanations
beside professional research. The supplement does not change the baseline
record/digest, numeric receipts, ratings, research quality or original Markdown.
Main report and evidence rail/drawer share the same explanation. Unsupported
historical formats retain their professional text rather than guessed meanings.

## Ownership and routes

Canonical models: [`_report_explanation.py`](../../tradingagents/agents/schemas/_report_explanation.py).
Financial definitions, number formatting and scoped targets:
[`research/report_explanation.py`](../../tradingagents/research/report_explanation.py).
Generation: [`execution/report_explanation.py`](../../tradingagents/execution/report_explanation.py).
Projection: [`web/report_explanation.py`](../../tradingagents/web/report_explanation.py).

`GET /api/runs/{run_id}/reader/explanations` only reads the validated public
baseline, deterministic display and saved supplement; no models, data retrieval
or writes. New Web native studies carry the creation metadata marker
`report_explanation_policy=plain-language-report-v1`. After publication and run
completion the manager schedules the bounded job with frozen quick-model settings.
The marker is written only for `research_profile == "evidence_v1"`, and that
scheduling is best-effort: a failure is suppressed and never changes the run's
terminal state. Historical runs never gain this marker on read, recovery or
startup. They receive supported indicator definitions and number formatting only.

`POST` to the same endpoint explicitly generates/retries an eligible completed
new-study supplement, returning `202` or a safe `409` rejection. Pending/valid jobs
are reused. Historical generation is rejected. Opening Reader and selecting
evidence never POST. Failed/interrupted jobs require an explicit user retry.

## Financial and numeric boundaries

Fractions become percentages; already-percent units are not multiplied again.
Positive quantiles retain their sign. Amounts use yuan, ten-thousand yuan or
hundred-million yuan; share prices use yuan/share. Normally show at most two
decimal places; tiny nonzero values retain significant digits. Unavailable values
never become zero. Keep periods, windows and samples; disclosures preserve the
saved professional representation. Formatting cannot restore upstream precision.

Assets are accounting resources, not all cash; liabilities are broader than
borrowings; revenue, profit and operating cash flow are different. Negative
operating cash flow neither proves an equal accounting loss nor establishes its
cause. Reporting-period length is not inferred from its end date.

Volatility, historical quantiles/ES, drawdown, ATR and Beta describe the saved
historical sample. They do not establish fair value, future return/probability or
maximum future loss. Interpolated quantiles do not guarantee an exact count of
observations below their threshold. Source selectors are qualified separately
from executed-check replay; normal numeric-publication validation is unchanged.

## Model, persistence and failure boundaries

The request-only [`model_request.py`](../../tradingagents/execution/model_request.py)
transport is shared with native execution, preserving API/subscription support,
deadline/cancellation and the global semaphore. Supplements own their schema,
prompt, attempt journal and `aux.report_explanation` effort task. No model/provider
fallback is introduced. Original research stage counts exclude this reading aid.

Admit at most 32 whole targets and 32,000 input content characters, including
scoped dependencies. Prioritize judgement, reasons, conditions, dimensions and
next checks. Exclusions remain explicit. Each explanation plus uncertainty is at
most 240 characters. Model prose is qualitative; the existing numeric lexer
rejects unbound quantities while the host displays saved values separately.

One main call and at most one schema repair share a 120-second deadline. SDK
retries are disabled. Quota, login, permission, capability and request failures
are not replayed automatically. Persist each dispatch first; unknown outcome
counts as spent, missing usage remains null, and explicit retries retain history.

Jobs deduplicate by baseline/focus digests, target identity, language and policy.
Save results as an immutable `report-explanation` artifact referenced by the atomic
`supplements/report-explanation-v1.json` manifest. Neither native checkpoint nor
baseline is rewritten. GET verifies source/target hashes, references, model/config
identity and the result artifact hash. Corruption degrades only the supplement.
Interrupted jobs do not restart automatically. Execution remains single-service;
no cross-process writer guarantee is introduced.

Independently valid entries can survive with explicit partial coverage. Malformed
envelopes and duplicate targets require bounded repair. Structural and numeric
validation does not prove semantic fidelity or economic correctness. Prompts
require uncertainty, conditions, withdrawn viewpoints and missing synthesis to
remain explicit. The UI identifies incomplete/failed generation and retains the
professional report and supported rules. No new export format is introduced.
