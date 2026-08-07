# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradingAgents is a LangGraph-based multi-agent LLM financial trading analysis framework. This is **David's fork**, optimized primarily for the **China A-share market** as the main use case, with A-share data providers (tushare/akshare), Tavily news curation, an Evidence Steward gate, and other enhancements on top of upstream (TauricResearch/TradingAgents). Non-A-share tickers (US/crypto/commodity/forex) are supported but secondary.

The fork is synced to **upstream v0.3.1** (2026-07). It adopts upstream's architectural improvements (provider registry, verified data-access contract, symbol normalization, structured output, analyst execution planning) but strips team/enterprise-oriented expansion: **do not re-add** Bedrock, Kimi, Groq, Mistral, NVIDIA NIM, or Polymarket. FRED macro data is kept. The default LLM provider is **DeepSeek**.

## Common Commands

```bash
# Install (dev mode)
pip install -e .                          # base install
pip install -e ".[china]"                 # with A-share data sources (akshare, tushare)

# CLI entry
tradingagents                            # interactive CLI
tradingagents analyze                    # jump straight to analysis
python -m cli.main                       # equivalent
tradingagents inspect-preset <path>      # validate a workbench analyst preset

# Tests (local-only — tests/ is NOT tracked on GitHub; clone ships runnable code + docs only)
pytest                                    # all tests
pytest -m unit                            # unit tests only
pytest -m integration                     # integration tests (require external services)
pytest -m smoke                           # smoke tests
pytest tests/path/to/test_file.py         # single test file
pytest -k "test_name_pattern"             # filter by name

# Docker
docker compose up tradingagents           # run tradingagents service
docker compose --profile ollama up        # with local Ollama

# Local web workbench (localhost-only; requires the [web] extra + Node only for rebuild)
pip install -e ".[web]"                   # FastAPI/Uvicorn/RFC8785 + the approved LangGraph/checkpointer floor
tradingagents web                         # serve the built SPA at http://127.0.0.1:8000 (127.0.0.1 only; no --host)
tradingagents web --port 8765 --open      # custom port + open the browser
npm --prefix frontend run build          # rebuild frontend into tradingagents/web/static/ (run when src/ui changes)
npm --prefix frontend run typecheck      # strict TS check (tsc -b --noEmit)
npm --prefix frontend run test -- --run  # vitest unit tests
npm --prefix frontend run test:e2e       # Playwright against scripts/e2e_server.py; deterministic fake runner, no provider calls
```

## Core Architecture

### LangGraph Pipeline Flow

```
START → Analyst Team (sequential, configurable: market/social/news/fundamentals)
  → Evidence Steward (PASS / LOW_CONFIDENCE / FAIL_STOP; enriches via Tavily if thin)
  → Bull Researcher ↔ Bear Researcher (multi-round debate, judged by Research Manager)
  → Trader (produces transaction proposal)
  → Aggressive ↔ Conservative ↔ Neutral (risk management 3-way debate)
  → Portfolio Manager (structured final decision: Buy/Overweight/Hold/Underweight/Sell)
  → END
```

Key concepts:
- **Two LLM paths**: `deep_thinking_llm` (Research Manager and Portfolio Manager) and `quick_thinking_llm` (all other agents), both created in `TradingAgentsGraph.__init__`
- **Each Analyst node** is 3 sub-nodes: agent → conditional edge → tool node (loop) or clear node (proceed), defined in `GraphSetup.setup_graph()`
- **AgentState** (`tradingagents/agents/utils/agent_states.py`) is the single shared TypedDict state flowing through the entire graph — all agent outputs are written into it
- **Checkpoint/Resume**: via `langgraph-checkpoint-sqlite`, one SQLite DB per ticker; a crashed run can resume from the last successful node on the same ticker+date
- **Memory Log**: `TradingMemoryLog` persists decision logs; on the next same-ticker run, deferred reflection runs (fetch realized returns → LLM reflection → store for future agents)

### Key Modules

| Module | Responsibility |
|--------|---------------|
| `tradingagents/graph/` | LangGraph orchestration: graph construction, conditional routing, state propagation, checkpoint, reflection, signal processing |
| `tradingagents/agents/` | All LLM agent implementations + tool methods + Pydantic structured-output schemas |
| `tradingagents/dataflows/` | Data ingestion layer: vendor fallback chains, A-share supplementation, news curation, consistency/credibility detection |
| `tradingagents/llm_clients/` | LLM provider abstraction: factory pattern routing to OpenAI-compatible / Anthropic / Google / Azure |
| `tradingagents/default_config.py` | **Single source of truth for all configuration**, supports `TRADINGAGENTS_*` env-var overrides |
| `cli/` | Typer + Rich interactive CLI |
| `tests/` | pytest suite (130+ test files), conftest auto-injects dummy API keys. **Local-only** — not tracked on GitHub |

### Data Fetching Fallback Chain

Data calls route through `tradingagents/dataflows/interface.py` → `route_to_vendor()`:
- **A-share stock data**: mootdx → tushare (mootdx = TDX TCP 7709, no IP ban, primary; akshare removed from this chain; alpha_vantage is global-only via VENDOR_MARKETS; yfinance skipped for A-shares - needs VPN, poor coverage)
- **Non-A-share stock data**: yfinance → alpha_vantage (tushare/akshare/sina skipped)
- **A-share fundamentals/financial statements**: tushare → Sina direct (`quotes.sina.cn`, zero key) → alpha_vantage; the old akshare `stock_financial_report_sina` wrapper was replaced by the direct `china_data.get_*_sina` adapters (same underlying source, no SDK failure plane); `get_fundamentals` keeps akshare (`stock_financial_abstract`) as a fallback
- **Technical indicators**: local (A-share stockstats over mootdx/tushare OHLCV) → yfinance → alpha_vantage; the A-share local vendor replaces the old NO_DATA_AVAILABLE sentinel
- **News**: multi-source parallel fetch → deduplication → credibility scoring → cross-source consistency detection → curated output. A-share tickers add a keyless EastMoney stock-news fallback (`eastmoney_news.py`) after Tavily.
- Each tool method can be individually vendor-configured; tool-level config takes precedence over category-level

### LLM Provider Support

`factory.py` dispatches by provider name:
- OpenAI-compatible protocol: openai, xai, deepseek, qwen, glm, minimax, ollama, openrouter → `OpenAIClient`
- Anthropic protocol: anthropic, mimo → `AnthropicClient`
- Google Gemini: google → `GoogleClient`
- Azure OpenAI: azure → `AzureOpenAIClient`

### Fork-Specific Features (vs upstream)

1. **A-share support**: `tradingagents/dataflows/china_data.py` + `tradingagents/dataflows/mootdx_provider.py`; mootdx (TDX TCP 7709, no IP ban) is the primary A-share OHLCV source, tushare remains primary for fundamentals, akshare is the `get_fundamentals` fallback (yfinance is skipped — needs VPN, poor A-share coverage). A-share financial statements use Sina direct HTTP (`get_*_sina` in china_data.py) as the reliable fallback. Local identity resolution: tushare -> EastMoney push2 direct -> akshare -> yfinance.
2. **Tavily news**: `tradingagents/dataflows/tavily_news.py`, A-share query templates, topic fallback, domain/score filters
3. **Evidence Steward**: `tradingagents/agents/evidence_steward.py` + `tradingagents/dataflows/evidence.py`, assesses evidence sufficiency before downstream debate and enriches via Tavily when thin/contradictory/identity-ambiguous. Terminal verdicts are `PASS`, `LOW_CONFIDENCE`, and `FAIL_STOP`; `evidence_stop_on_fail` defaults to `False`, but hard identity conflicts and fatal core-data conditions remain unconditional stops. `LOW_CONFIDENCE` reaches Research/Portfolio Manager prompts as a conviction cap. Unexpected steward faults persist only the exception category, never raw exception text.
4. **News Advisor**: `tradingagents/dataflows/news_advisor.py`, LLM-driven (Agentic RAG reflection) coverage-gap analysis + targeted search
5. **Credibility Scoring**: `tradingagents/dataflows/credibility.py`, news source credibility scoring
6. **Cross-source Consistency**: `tradingagents/dataflows/consistency.py`, cross-source consistency detection
7. **Market Data Validator**: `tradingagents/dataflows/market_data_validator.py`, deterministic snapshot to ground numeric claims (stops LLM confabulation of prices/indicators)
8. **Symbol Normalization**: `tradingagents/dataflows/symbol_utils.py`, normalize commodity/forex/crypto/A-share tickers
9. **Progress events**: `tradingagents/dataflows/progress.py`, lightweight data-call progress events surfaced in the Chinese CLI
10. **Local web workbench**: `tradingagents web` (loopback-only) runs the real LangGraph via a React+TS+Vite SPA served by FastAPI (SSE). The reading surface is **progressive**: the completed-run view defaults to a `DecisionBrief` (rating/conclusion/drivers/risks) plus a six-stage **debate journey** timeline (analysts → evidence → research → trading → risk → portfolio) with measured round counts and a real-data insight strip; clicking a stage expands L2 **round cards** (LLM-generated topic/summary/keywords with estimated bull/bear conviction bars), and expanding a card loads L3 **two/three-lane full text** from the exact turn output artifacts. The summaries are generated post-completion by `tradingagents/web/debate_summary.py` using the run's `quick_think_llm` (background daemon thread + lazy fallback; failures degrade silently and never change a run's terminal state), persisted to `projections/debate-summary-v1.json` with per-round `sources` artifact ids. Run history is grouped into active/completed/failed (last 3, red, with error category)/terminated; failed runs open a `FailedRunView` with the categorized error while the event log stays browsable. While a run is live the UI shows `SwarmStatusCard` + `WorkflowMap` + `RunDisclosure` (input/reports/artifact index) and the selected turn drives a fixed Identity/Evidence/Prompt/Output inspector; the reader surface takes over only when the projection is terminal. The full audit timeline remains reachable via the opt-in `AuditReader` (complete report markdown). Non-A-share tickers get a yfinance reachability preflight (`tradingagents/web/connectivity.py`): an unreachable Yahoo probe fails fast with a 503 `yfinance_unreachable` before a run is created (VPN needed); A-share tickers skip it. Frontend lives in `frontend/`; its committed build output is `tradingagents/web/static/` so an installed wheel serves without Node. Backend is under `tradingagents/observability/` + `tradingagents/web/` + `tradingagents/execution/runner.py`. Rebuild and commit static drift whenever `frontend/src` changes. The e2e suite (`npm --prefix frontend run test:e2e`) drives `scripts/e2e_server.py`, whose fake runner emits deterministic typed public outputs and a stubbed debate summary.
11. **A-share data source overhaul**: mootdx (TDX TCP 7709, no IP ban) is the primary A-share OHLCV source; tencent (qt.gtimg.cn) provides realtime PE/PB/market-cap; specialty data (dragon-tiger/lockups/block-trades/shareholder-counts/limit-up/break-board/limit-down/prev-limit-up pools) uses EastMoney direct HTTP (datacenter/push2ex) via `china_specialty_em.py` with SSE/SZSE official backups; new capabilities: research reports (reportapi + THS consensus EPS), industry/concept boards, ETF option T-quotes/Greeks (Sina), market hot-list/concept-hits (THS+EastMoney). akshare retained only for macro + interactive Q&A. CLS telegraph revived with local signing (zero key).

## Design Principles

- **First-principles reasoning**: When making design decisions, derive from fundamental requirements and constraints rather than mimicking existing implementations
- **Stop and ask when uncertain**: If anything is unclear or unconfirmed, pause and clarify before proceeding — never assume
- **Single source of truth for config**: All configurable items must be managed through `default_config.py`'s `DEFAULT_CONFIG` dict + `_ENV_OVERRIDES` mapping
- **Structured output**: Research Manager / Trader / Portfolio Manager use Pydantic schemas to constrain LLM output; `render_*` functions convert back to markdown for downstream consumers
- **Evidence-aware degradation**: ordinary provider gaps and thin coverage should remain explicit and continue as `LOW_CONFIDENCE`; hard identity conflicts and fatal core-data conditions remain `FAIL_STOP`. Never erase limitations or silently promote degraded evidence to `PASS`
- **A-share-first identity resolution**: A-share tickers resolve identity via the local chain (tushare -> EastMoney push2 direct -> akshare -> yfinance) in `resolve_canonical_company_profile()`; non-A-share tickers use upstream `resolve_instrument_identity()` (yfinance). The branch lives in `TradingAgentsGraph.resolve_instrument_context()`, which also normalises company names / multi-format codes via `company_resolution.resolve_input_to_ticker()`. Never bypass the local chain for A-shares - yfinance coverage is poor and often returns wrong/English names.
