# Web research: use and recovery

Status: Current

This is the operating guide for the maintained local A-share Web workbench.
For module ownership read [architecture](../../ARCHITECTURE.md); for machine boundaries read the
[research contract](../contracts/research-record.md). Historical plans are not setup instructions.

## Start Web research

Requires Python 3.10+. Reuse the existing Conda environment:

```bash
conda activate tradingagents
python -m pip install -e ".[china,web]" --index-url https://pypi.org/simple
cp .env.example .env  # First setup only; preserve an existing local file.
tradingagents web --port 8765 --open
```

If no such environment exists, create it once as shown in the [README](../../README.md#快速开始).
The server binds only to `127.0.0.1` and includes its SPA; Node.js is not needed at runtime.
Run one server per run-store directory. Changes to environment configuration require a restart.

## Model settings

Keep credentials in the ignored `.env`, never in reports or committed examples.
The launcher loads repository `.env` with override, then `.env.enterprise` as fallback;
direct package launches use their working directory and preserve exported environment values.
The Web server does not load the CLI's `tradingagents.local.json`.

| Purpose | Configuration |
| --- | --- |
| Research model | Select provider plus specialist/challenge and synthesis models in the workbench. API providers need their own key. Defaults are DeepSeek `deepseek-flash` for both tiers. Tencent Hunyuan (`hunyuan`, TokenHub endpoint, `HUNYUAN_API_KEY`) offers `hy4-preview`, uses JSON Schema output and keeps the model's default `high` reasoning; it accepts no stage effort. |
| Stage models (optional) | The collapsed **分阶段模型（高级）** panel overrides provider, model and effort for operating, event and market specialists, challenge and synthesis. Unset rows inherit the two tiers; each response follows its specialist. Every selected provider needs its key; ChatGPT stages share the signed-in account. |
| ChatGPT research | Choose ChatGPT subscription and complete official sign-in; use the returned account catalog. See [account setup](chatgpt-subscription.md). |
| Search, independently of research model | `DEEPSEEK_API_KEY` for Search/Fetch and `TAVILY_API_KEY` or comma-separated `TAVILY_API_KEYS` for Search/Extract. ChatGPT login supplies neither. |
| Optional data access | Tushare token/entitlement can supply fallback data and valuation history; public default sources remain independent. See [data capabilities](a-share-data-capabilities.md). |
| Disable new research | `TRADINGAGENTS_EVIDENCE_ENABLED=false`; saved reads and compatible recovery remain available. |

Missing search credentials degrade coverage rather than disable available dedicated sources.
Set `TRADINGAGENTS_EVIDENCE_SEARCH_ENABLED=false` before starting the server to disable independent
Search/Fetch for new runs. Research-model calls and dedicated data sources remain available.
Programmatic callers can set `effective_config.evidence_search_enabled`; there is no Web UI selector.
Compatible resume retains the saved switch and budgets.

DeepSeek defaults to enabled thinking/high effort. Environment controls include
`TRADINGAGENTS_DEEPSEEK_THINKING`, `TRADINGAGENTS_DEEPSEEK_REASONING_EFFORT`,
`TRADINGAGENTS_OPENAI_REASONING_EFFORT` and optional `TRADINGAGENTS_LLM_MAX_TOKENS`.
ChatGPT effort support is model-dependent; its output-cap omission is intentional. Google maps the
shared output cap to `max_output_tokens`, and Azure forwards `max_tokens`; provider-side acceptance
and enforcement depend on the selected model. A stage `effort` replaces the former task-effort mapping and lands on the
selected provider's own setting; providers without one reject it. A failed stage call fails under the normal rules and never
falls back to another model. [stage_models.py](../../tradingagents/llm_clients/stage_models.py) owns stage keys, resolution and
valid efforts; runs freeze the resolved policy for resume and the audit configuration view.

Fresh V9 research sends strict structured output on SIWC/OpenAI and JSON mode on the existing
DeepSeek Chat Completions route. Canonical evidence and numeric checks still apply; only V9 requests are supported. A successful small schema probe is separate from complete real-model
research acceptance. See the [output contract](../contracts/research-record.md) for boundaries.

## Create a study

1. Enter a supported A-share code or a company name that resolves to one instrument.
2. Choose model/account configuration and output language, then start research. The server uses the
   current Asia/Shanghai date; there is no date selector.
3. Optionally supply a supplementary focus, trimmed to 400 Unicode code points. The independent
   company baseline excludes this text; a saved-evidence response follows it and cannot rewrite it.

New studies assess company investment attractiveness through operations, valuation, events and market
risk. They use `evidence_v1` / V9 and publish an independent Insight record. There are no native analyst,
debate-depth, preset or horizon selectors. Requests containing retired profiles, modes or scheduling
fields return 422. Reading, retrying or resuming an unsupported saved workflow returns 409
`unsupported_research_version`; its files remain untouched.

API clients use `POST /api/runs`; [RunCreateRequest](../../tradingagents/web/schemas.py) is the request
source. Omit `analysis_date` for current research. Explicit dates remain accepted for compatible API
callers; saved runs keep their original cutoff. Omit legacy scheduling overrides. A date is not proof that today's source values
were available on that historical date: unarchived profiles, quotes or factor vintages may be unavailable.

## Batch research

A batch accepts 1–8 companies with shared current cutoff, focus, provider/models and language. Every child is an
independent durable run. Single/batch jobs share a FIFO scheduler; global concurrency defaults to 3
and may be 1, 2 or 3. Lowering it does not interrupt admitted work.

Failures stay isolated and are not automatically retried. Batch cancellation cooperatively cancels
active children and marks queued children cancelled. Deleting a terminal batch preserves its runs.
Completion notifications require browser permission and an available browser; cancellation alone
produces no single-run completion notice. Queued work survives reload/startup recovery.

## Evidence and workflow

Dedicated APIs come first for identity and quantitative inputs; bounded dual search provides context
and attempts missing fields. Qualified sources feed isolated specialists, bounded supplementary collection, one critique/reply
round and synthesis. Source availability is distinct from
fact qualification. Reposts do not create independent confirmation; titles/snippets do not prove delivery.

Fresh studies present all qualified fact cards and selected exact saved-source passages. Models return
four-field Insights plus optional outer `search_requests` and `capability_requests`; code resolves
references and renders numbers. Capability cards are short, role-filtered and host-routed; `news_search`
stays on the dual-search path, while structured cards reuse a-stock-data-aligned adapters. The
requestable set now also includes bounded valuation history, today's THS northbound aggregate and Wind
risk metrics when the local CLI is configured; financial-detail and peer-context stay prefetch-only. Each
supplement round runs capability calls before web questions with separate budgets; capability work still
runs when web search is disabled. At most three rounds apply; new gaps from reanalysis consume remaining
rounds instead of resetting the budget. Changed evidence requires affected roles to reanalyse.

Capability calls are reviewable from the saved run: accepted requests (card id, query, gap reason) are
frozen in the research journal as `insight.capability_requests.<role>[.supplement_<round>]`, each
executed round's admitted increment under the `insight.capability.round.<round>` result key, and each
dispatch is a `supplement_capabilities` budget attempt whose stage names the role and card. Rejections,
empty results and card/role limits remain typed `capability_*` codes in the saved report gaps; none of
them proves the event did not happen. The Audit Center capabilities section lists each gateway batch
with its admitted/empty/budget/failure state, reason codes, providers and saved result id, in addition
to the older source-degradation summaries.
A review may explicitly find no effective counterevidence; missing or failed review remains visible.
The latter does not prove the Insight correct. See [V9 semantics](../contracts/research-record.md#insight-first-v9).

Sources retain identity, dates, units and coverage. SZSE's full-month calendar is authoritative for all
A-share exchanges; Tencent index dates and TDX witness gaps/disputes, with Tushare as last fallback.
Missing bars are not automatically holidays. See [source rules](a-share-data-capabilities.md).

## Read a result

| Display/state | Meaning |
| --- | --- |
| Running stage output | A qualified saved proposal; it may be revised and is not a final report. |
| `completed` | Execution/publication finished; it does not prove complete evidence or correct judgement. |
| Reader `insight_ready` | The saved V9 Insight report is readable. |
| Insight `pending` / `excluded` | Unsupported, withdrawn or superseded work remains visible but cannot support the overall judgement. |
| No overall rating | Overall synthesis was unavailable or its references/quantities failed checks; valid independent Insights remain. |

Start with stance and its limits, then supporting/opposing reasons and change conditions. Use the
bound evidence panel to check source text, dates and units. Process/Agent views explain contributions;
the full record retains detail omitted from the first screen. A passed arithmetic check answers its
specific question, not the entire hypothesis or an economic cause.

Native Reader, evidence expansion and Markdown use saved content, without new research calls.
The optional focus is separate. Web automatically schedules an independent plain-language explanation
job after report completion; explanation coverage is not an acceptance gate. A failed explanation leaves
professional text available. GET reads saved explanations; POST to the explanation endpoint explicitly
starts or retries an eligible job without changing the baseline report.

Default V9 explanation jobs select at most 32 Insight targets within a 32,000-character target budget
and run for up to 120 seconds, with one repair opportunity. Existing V9 runs marked
`evidence-packets-v1` use the batched policy: up to 16 targets per batch, 24 requests and five minutes
overall, with one missing-item repair per batch. Batched retry retains its original deadline, request
history and accepted entries; it does not reset exhausted limits. Earlier workflow records are unsupported.
Technical diagnostics are for execution failures, not a quality score.

## Budget, cancellation and recovery

A new study defaults to a 900-second active deadline excluding scheduler queue time; saved requests
without a frozen value keep 300 seconds. An expired deadline fails the run as a timeout, not a user
cancellation. Search, HTTP, review and
model pools have independent ceilings; see [shared limits](../contracts/research-record.md#search-and-execution-limits).
Missing usage remains unknown; authorization counts are not confirmed charges.

- Interrupted runs may resume the same ID using their saved request, versions, inputs and budgets.
- Failed/cancelled runs need a new study or an allowed retry; retry creates a new run rather than
  rewriting the old report. Only supported V9 runs are eligible for retry or resume.
- A dispatched request without a saved outcome remains spent and is not automatically repeated.
- Cancellation before publication authorization prevents publication; after authorization, a late
  cancellation is rejected so the committed candidate can finish publication.

The history sidebar includes queued studies and can load older pages. Resuming the selected run
refreshes its view and event stream; temporary disconnects retry within a bounded budget. Active
batch members cannot be deleted individually. A second Web launcher cannot own the same run store.
Open the workbench through its loopback address; foreign Host/Origin requests are rejected.

## Saved data and troubleshooting

Runs live under `~/.tradingagents/web/runs/`; the stored report is `reports/complete_report.md`.
Credentials live separately. Do not clear run directories to resolve model or source errors.
For safe diagnostics and offline reconstruction use [observability/replay](observability-replay.md).
Only V9 runs are supported. Earlier workflow execution, reading and recovery have been removed; old files stay on disk without conversion. CLI uses the same runner; see [terminal operations](cli-research.md).

<a id="official-document-admission"></a>
<a id="explicit-development-capture"></a>
