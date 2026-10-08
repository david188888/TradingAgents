# Contributing

TradingAgents is a Python 3.10+ project with a React/TypeScript workbench. Contributions should keep the local-first, research-only product boundary intact and should preserve existing dirty work in unrelated files.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[china,web,dev]"
npm --prefix frontend ci
```

Copy `.env.example` to `.env` for Web credentials and supported environment defaults. The retained CLI can additionally load `tradingagents.config.example.json` copied to the ignored `tradingagents.local.json`; the Web server does not load that JSON. Never commit API keys, provider responses, local run stores, or private datasets. Coding Agents should read [AGENTS.md](AGENTS.md) and the applicable scoped guide before editing.

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

The pytest, Vitest and Playwright suites are tracked and available in fresh
clones after contributor setup. Before the first end-to-end run, execute
`npx playwright install chromium` from `frontend/` and build the SPA. The
fixture server uses `python`; set `TRADINGAGENTS_E2E_PYTHON` to the contributor
interpreter when needed. Linux hosts may also need Playwright browser system
dependencies. See the [frontend guide](frontend/AGENTS.md).

No GitHub Actions workflows are tracked in this fork. Install the local Ruff
commit hook once with `pip install pre-commit && pre-commit install`.
Run relevant checks locally and verify remote checks/review requirements when
publishing; absent checks are not CI success. Documentation changes require
`python scripts/check_agent_docs.py` and `git diff --check`. Frontend install,
typecheck/build and tests apply to changes affecting that layer.

After changing `frontend/src/`, `npm --prefix frontend run build` must be run and the generated `tradingagents/web/static/` output must remain in sync. Do not edit generated assets by hand.

## Documentation Impact

Use the [documentation index](docs/README.md) to classify the change before opening a PR.

- Product overview: keep the Chinese [README.md](README.md) and [English README](README.en.md) aligned and concise. Budgets, version-specific execution rules and API/recovery details belong in focused documents. `README.zh-CN.md` is a compatibility pointer; `pyproject.toml` uses the English README as its package description.
- Public request, response, event, artifact, or runtime semantics: update the canonical source, consumers, [contract index](docs/contracts/README.md), and affected current-state docs.
- Module boundaries or execution flow: update [ARCHITECTURE.md](ARCHITECTURE.md) and the relevant scoped `AGENTS.md`.
- Reader, Companion, or Audit behavior: update [Reader architecture](docs/architecture/research-reader.md) and its contract sources.
- A-share data capability or provider behavior: update the focused data reference and any applicable plan or decision record.
- Temporary implementation work: update the owning plan; do not present the plan as shipped architecture.

If a change has no documentation impact, state `No documentation impact` in the PR description. Otherwise name the updated documentation surface explicitly.

## PR Hygiene

Keep changes scoped, explain compatibility implications, and include the commands used for validation. Do not commit local secrets, ignored test artifacts, run-store data, generated caches, or unrelated dirty files. A clean documentation diff should pass `git diff --check`.

When Git publication is authorized, use branch → PR → merge after applicable
local checks and required remote checks/reviews pass. Stop for material scope
uncertainty, conflicts, failed/pending checks or missing required review; never
bypass protections. No separate merge confirmation is needed within that scope.

Before handing off, verify `git status --short`, inspect the complete diff, and confirm that any changed public surface has both consumer updates and a current documentation pointer. Do not bypass or weaken the pre-commit Ruff gate to land a change.
