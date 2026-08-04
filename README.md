# TradingAgents

TradingAgents is a **LangGraph-based multi-agent LLM financial trading analysis framework**. This is David's fork, optimized primarily for the **China A-share market**, with A-share-native data sources, evidence validation, and a local web workbench.

It is a research tool, not a broker, portfolio accounting system, or source of investment advice.

## Pipeline

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

Four analysts gather complementary evidence. The Evidence Steward validates the research package before the Bull and Bear researchers debate it. The Research Manager produces an investment plan, the Trader proposes an action, three risk roles challenge that proposal, and the Portfolio Manager returns the final decision (Buy / Overweight / Hold / Underweight / Sell).

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

The workbench binds only to `127.0.0.1` and runs the real TradingAgents graph via a React/TypeScript frontend with a FastAPI + SSE backend. It groups all 13 roles into six workflow stages with typed edges, renders narrative artifacts as sanitized Markdown, and provides a **reader-first surface** — a **DecisionBrief** and **AuditReader** for inspecting each turn's identity, evidence, prompt, and output. The run history sidebar lets you browse and revisit completed analyses. The bundled frontend does not require Node.js at runtime.

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

See [CLAUDE.md](CLAUDE.md) for the authoritative reference on architecture, data fallback chains, and design principles.

- [A-share data capabilities](docs/a-share-data-capabilities.md)
- [Observability and replay](docs/observability-replay.md)
- [Workbench presets](docs/workbench-presets.md)

## License

This project is available under the terms in [LICENSE](LICENSE).
