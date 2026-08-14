# TradingAgents

TradingAgents is a **LangGraph-based multi-agent LLM financial trading analysis framework**. This is David's fork, optimized primarily for the **China A-share market**, with A-share-native data sources, evidence validation, and a local web workbench.

It is a research tool, not a broker, portfolio accounting system, or source of investment advice.

## Pipelines

The learning-research path is the default product direction for the local workbench:

```
Market / Social / News / Fundamentals Analysts
                    ↓
             Evidence Steward
                    ↓
          Bull ↔ Bear Research Debate
                    ↓
             Research Manager
                    ↓
              ResearchCaseV2
                    ↓
          Thesis Diff + Reader Surface
```

It supports company research and holding review without producing orders, target
positions, or Buy/Hold/Sell instructions. The upstream-compatible legacy graph
branch remains retained for compatibility with older runs and legacy boundaries;
current typed request modes are only `company_research` and `holding_review`, and
the CLI defaults to `company_research`. Both typed modes bypass Trader and the
three-role risk debate, then terminate through Portfolio Manager.

```
Retained legacy compatibility graph branch, not selected by current typed request modes

Market / Social / News / Fundamentals Analysts
                    ↓
             Evidence Steward
                    ↓
          Bull ↔ Bear Research Debate
                    ↓
             Research Manager
                    ↓
                  Trader
                    ↓
 Aggressive ↔ Conservative ↔ Neutral Risk Debate
                    ↓
             Portfolio Manager
```

Four analysts gather complementary evidence. The Evidence Steward validates the
research package before the Bull and Bear researchers debate it. In learning modes,
the Research Manager produces evidence-bound claims that are assembled into a
typed Research Case and projected into the Reader. Trader and the three-role
risk debate remain in the retained compatibility branch; Portfolio Manager is the
shared terminal convergence for typed and legacy routes.

## Quick Start

```bash
# Requirements: Python 3.10+, API credentials for LLM and data services
git clone https://github.com/david188888/TradingAgents.git
cd TradingAgents
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[china,web]"       # full install with A-share data + web workbench

# Create local config (both are .gitignored)
cp .env.example .env
cp tradingagents.config.example.json tradingagents.local.json

# Start the interactive CLI
tradingagents
# or jump straight to analysis
tradingagents analyze
```

Configuration is resolved from environment variables (`TRADINGAGENTS_*`), a local JSON file, or interactive prompts. The default LLM provider is DeepSeek. See `tradingagents/default_config.py` and `.env.example` for all options.

## Local Web Workbench

```bash
tradingagents web                          # serve at http://127.0.0.1:8000
tradingagents web --port 8765 --open       # custom port + open browser
```

The workbench binds only to `127.0.0.1` and runs the real TradingAgents graph via a React/TypeScript frontend with a FastAPI + SSE backend. It groups all 13 roles into six workflow stages with typed edges and renders narrative artifacts as sanitized Markdown. The reading surface is **progressive**: a completed run defaults to a **DecisionBrief** (rating / conclusion / drivers / risks) above a six-stage **debate journey** timeline — click a stage to expand **round cards** (LLM-generated topic, summary, keywords, bull/bear conviction bars), then expand a card to the full two/three-lane debate text. Run history groups active / completed / failed runs (recent failures keep their error category). Terminal runs use an opt-in **Audit Center** with summary-first, single-record detail loading; live runs keep a separate **real-time inspector**. The bundled frontend does not require Node.js at runtime.

Rebuild the frontend from source when changing `frontend/src/`:
```bash
npm --prefix frontend run build
```

## Differences from Upstream

This fork extends [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) with:

- **A-share-first data path**: mootdx (TDX TCP, no IP ban) for primary OHLCV, tushare for fundamentals, EastMoney/SSE/SZSE for specialty data (dragon-tiger, lockups, block trades, limit-up pools, shareholder counts), Tencent for realtime PE/PB/market-cap, Sina for ETF options and financial statement fallback. yfinance is skipped for A-shares.
- **Evidence Steward gate**: validates evidence sufficiency before the debate phase. Issues `PASS`, `LOW_CONFIDENCE`, or `FAIL_STOP` verdicts and enriches thin evidence via Tavily.
- **Tavily news curation**: A-share query templates with topic fallback, domain/score filters.
- **Credibility scoring & cross-source consistency**: news source quality scoring and multi-source consistency detection.
- **Symbol normalization**: commodity/forex/crypto/A-share ticker normalization.
- **Local web workbench**: reader-first observability surface (described above).

## Data Locations

Persistent data lives under `~/.tradingagents/`:

| Data | Default path |
| --- | --- |
| Reports and logs | `~/.tradingagents/logs/` |
| Decision memory | `~/.tradingagents/memory/trading_memory.md` |
| Web workbench runs | `~/.tradingagents/web/runs/` |

## Documentation

Start with the shortest path for the task at hand:

1. [Documentation index](docs/README.md) for the repository map and document ownership.
2. [Current architecture](ARCHITECTURE.md) and [product context](docs/context.md) for system boundaries.
3. [Agent working rules](AGENTS.md) before changing code or configuration.
4. [Contract index](docs/contracts/README.md) before changing a public request, artifact, event, or API shape.
5. [Research Reader architecture](docs/architecture/research-reader.md) for the typed learning-research path.

Focused references:

- [A-share data capabilities](docs/a-share-data-capabilities.md)
- [Observability and replay](docs/observability-replay.md)
- [Workbench presets](docs/workbench-presets.md)
- [Legacy composite reference](docs/learning-research-reader.md) (migration reference; not the canonical ownership map)
- [Contributing](CONTRIBUTING.md) for validation and documentation-impact rules

Plans and reviews are deliberately kept separate from current-state documentation. Use the [documentation index](docs/README.md) to classify them before relying on their claims.

## License

This project is available under the terms in [LICENSE](LICENSE).
