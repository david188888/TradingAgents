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
positions, or Buy/Hold/Sell instructions. The upstream-compatible legacy path is
still available for older runs and CLI workflows:

```
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
typed Research Case and projected into the Reader. Trader and risk/portfolio roles
remain part of the legacy pipeline only.

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

The workbench binds only to `127.0.0.1` and runs the real TradingAgents graph via a React/TypeScript frontend with a FastAPI + SSE backend. It groups all 13 roles into six workflow stages with typed edges and renders narrative artifacts as sanitized Markdown. The reading surface is **progressive**: a completed run defaults to a **DecisionBrief** (rating / conclusion / drivers / risks) above a six-stage **debate journey** timeline — click a stage to expand **round cards** (LLM-generated topic, summary, keywords, bull/bear conviction bars), then expand a card to the full two/three-lane debate text. Run history groups active / completed / failed runs (recent failures keep their error category), and the opt-in **AuditReader** still exposes the complete report. The bundled frontend does not require Node.js at runtime.

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

See [CLAUDE.md](CLAUDE.md) for repository-wide development rules and data fallback
chains. The current product contract, implementation status, and remaining Reader
roadmap live in one maintained document:

- [Learning research and Reader](docs/learning-research-reader.md)
- [A-share data capabilities](docs/a-share-data-capabilities.md)
- [Observability and replay](docs/observability-replay.md)
- [Workbench presets](docs/workbench-presets.md)

## License

This project is available under the terms in [LICENSE](LICENSE).
