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
The Web server does not load the retained CLI's `tradingagents.local.json`.

| Purpose | Configuration |
| --- | --- |
| Research model | Select provider plus specialist/challenge and synthesis models in the workbench. API providers need their own key. Defaults are DeepSeek `deepseek-flash` for both tiers. |
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
and enforcement depend on the selected model. Task-effort mappings are programmatic/legacy CLI settings, not Web selectors;
[task_effort.py](../../tradingagents/llm_clients/task_effort.py) owns valid tasks and values.

## Create a study

1. Enter a supported A-share code or a company name that resolves to one instrument.
2. Choose analysis date, model/account configuration and output language, then start research.
3. Optionally supply a supplementary focus, trimmed to 400 Unicode code points. The independent
   company baseline excludes this text; a saved-evidence response follows it and cannot rewrite it.

New studies assess company investment attractiveness through operations, valuation, events and market
risk. They use `evidence_v1` / V8 and publish a V2 research record. There are no native analyst,
debate-depth, preset or horizon selectors. Earlier catalyst/holding scopes are read/resume only;
new old-mode requests return 422, and retired profiles return 410.

API clients use `POST /api/runs`; [RunCreateRequest](../../tradingagents/web/schemas.py) is the request
source. Omit legacy scheduling overrides. An analysis date is not proof that today's source values
were available on that historical date: unarchived profiles, quotes or factor vintages may be unavailable.

## Batch research

A batch accepts 1–8 companies with shared date, focus, provider/models and language. Every child is an
independent durable run. Single/batch jobs share a FIFO scheduler; global concurrency defaults to 3
and may be 1, 2 or 3. Lowering it does not interrupt admitted work.

Failures stay isolated and are not automatically retried. Batch cancellation cooperatively cancels
active children and marks queued children cancelled. Deleting a terminal batch preserves its runs.
Completion notifications require browser permission and an available browser; cancellation alone
produces no single-run completion notice. Queued work survives reload/startup recovery.

## Evidence and workflow

Dedicated APIs come first for identity and quantitative inputs; bounded dual search provides context
and attempts missing fields. Qualified sources feed isolated specialists, one challenge/check/reply
sequence, up to three supplementary rounds and one synthesis. Source availability is distinct from
fact qualification. Reposts do not create independent confirmation; titles/snippets do not prove delivery.

Sources retain identity, dates, units and coverage. SZSE's full-month calendar is authoritative for all
A-share exchanges; Tencent index dates and TDX witness gaps/disputes, with Tushare as last fallback.
Missing bars are not automatically holidays. See [source rules](a-share-data-capabilities.md).

## Read a result

| Display/state | Meaning |
| --- | --- |
| Running stage output | A qualified saved proposal; it may be revised and is not a final report. |
| `completed` | Execution/publication finished; it does not prove complete evidence or correct judgement. |
| Reader `ready` | The saved report is readable. |
| `partial` / `LOW_CONFIDENCE` | Coverage, accepted analysis or unresolved risks limit the research. |
| `analysis_unrated` / no overall rating | Usable analysis exists, but overall/critical synthesis or evidence gates do not support a rating. |
| `specialist_summary` / `basic_report` | Synthesis was unusable; saved specialist findings or basics remain, explicitly without a fabricated overall decision. |

Start with stance and its limits, then supporting/opposing reasons and change conditions. Use the
bound evidence panel to check source text, dates and units. Process/Agent views explain contributions;
the full record retains detail omitted from the first screen. A passed arithmetic check answers its
specific question, not the entire hypothesis or an economic cause.

Native Reader, evidence expansion and Markdown use saved content, without new research calls.
The optional focus is separate. New-study plain-language explanations run independently after completion;
a failed explanation leaves professional text available and requires explicit retry. Historical reading
does not generate a new explanation. Technical diagnostics are for execution failures, not a quality score.

## Budget, cancellation and recovery

A study defaults to a 300-second active deadline excluding scheduler queue time. Search, HTTP, review and
model pools have independent ceilings; see [shared limits](../contracts/research-record.md#search-and-execution-limits).
Missing usage remains unknown; authorization counts are not confirmed charges.

- Interrupted runs may resume the same ID using their saved request, versions, inputs and budgets.
- Failed/cancelled runs need a new study or an allowed retry; retry creates a new run rather than
  rewriting the old report. Old modes cannot be retried as newly created old-mode studies.
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
Historical version behavior, presets and external classic packages are in the
[compatibility reference](catalyst-research.md).

<!-- Compatibility anchors for existing section links. -->
<a id="current-v8-search-execution"></a>
<a id="explicit-development-capture"></a>
<a id="native-valuation-qualification"></a>
<a id="official-document-admission"></a>
<a id="v5-minimum-sufficient-evidence"></a>
<a id="v6-independent-baseline-and-supplementary-focus"></a>
<a id="v7-unified-company-investment-research"></a>
<a id="web-evidence-driven-research"></a>
