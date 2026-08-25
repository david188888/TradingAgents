# Contributing

TradingAgents is a Python 3.10+ project with a React/TypeScript workbench. Contributions should keep the local-first, research-only product boundary intact and should preserve existing dirty work in unrelated files.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[china,web,dev]"
npm --prefix frontend ci
```

Copy `.env.example` to `.env` and `tradingagents.config.example.json` to `tradingagents.local.json` for local configuration. Both local files are ignored. Never commit API keys, provider responses, local run stores, or private datasets.

## Scoped Validation

Choose checks that match the change:

```bash
python scripts/check_agent_docs.py
python -m pytest -m unit
python -m pytest
ruff check .
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

There is no remote CI in this fork. The commit gate is pre-commit: install it once with `pip install pre-commit && pre-commit install`, and Ruff runs against every `git commit`. Test assets (pytest, Vitest, and Playwright specs plus their configs) are tracked in the repository, so the validation commands above all work on a fresh clone. Passing the relevant checks locally is the bar for merging; `python scripts/check_agent_docs.py` must be run manually when documentation surfaces change.

After changing `frontend/src/`, `npm --prefix frontend run build` must be run and the generated `tradingagents/web/static/` output must remain in sync. Do not edit generated assets by hand.

## Documentation Impact

Use the [documentation index](docs/README.md) to classify the change before opening a PR.

- Public request, response, event, artifact, or runtime semantics: update the canonical source, consumers, [contract index](docs/contracts/README.md), and affected current-state docs.
- Module boundaries or execution flow: update [ARCHITECTURE.md](ARCHITECTURE.md) and the relevant scoped `AGENTS.md`.
- Reader, Companion, or Audit behavior: update [Reader architecture](docs/architecture/research-reader.md) and its contract sources.
- A-share data capability or provider behavior: update the focused data reference and any applicable plan or decision record.
- Temporary implementation work: update the owning plan; do not present the plan as shipped architecture.

If a change has no documentation impact, state `No documentation impact` in the PR description. Otherwise name the updated documentation surface explicitly.

## PR Hygiene

Keep changes scoped, explain compatibility implications, and include the commands used for validation. Do not commit local secrets, ignored test artifacts, run-store data, generated caches, or unrelated dirty files. A clean documentation diff should pass `git diff --check`.

Before handing off, verify `git status --short`, inspect the complete diff, and confirm that any changed public surface has both consumer updates and a current documentation pointer. Do not bypass or weaken the pre-commit Ruff gate to land a change.
