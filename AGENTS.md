# TradingAgents Working Guide

This file is the operational entry point for contributors and coding agents.
Read [README.md](README.md) for product setup, [ARCHITECTURE.md](ARCHITECTURE.md)
for the current system map, and [docs/README.md](docs/README.md) for detailed
references.

## Repository Map

- `cli/`: Typer commands and interactive terminal adapter.
- `tradingagents/`: Python package. See [tradingagents/AGENTS.md](tradingagents/AGENTS.md).
- `frontend/`: React workbench source. See [frontend/AGENTS.md](frontend/AGENTS.md).
- `tradingagents/web/static/`: generated SPA assets served by the Python package.
- `tests/`, frontend test files/configuration, and `frontend/e2e/`: optional
  local-only scaffolding when present; the public fork does not track them.
- `docs/`: focused operational references, plans, and reviews. Plans and reviews are not
  current-state architecture sources.

## Setup And Commands

Python 3.10 or newer is required. A contributor install with development
tooling is:

```bash
pip install -e ".[china,web,dev]"
```

Public, fresh-clone checks are:

```bash
python scripts/check_agent_docs.py
ruff check tradingagents cli scripts/check_agent_docs.py
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Run the following only when the corresponding local scaffolding exists; these
paths are not tracked by the public fork:

```bash
python -m pytest
python -m pytest -m unit
npm --prefix frontend run test -- --run
npm --prefix frontend run test:e2e
```

The supported user entry points are `tradingagents analyze` and
`tradingagents web --port 8765 --open`. The latter is a loopback-only local
workbench; it binds to `127.0.0.1`.

## Change Routing

| Change | Read and update as needed |
| --- | --- |
| Public Python request, result, artifact, or runtime contract | `tradingagents/execution/models.py`, `tradingagents/agents/schemas/`, `tradingagents/runtime/`, consumers and projections |
| Graph roles, routing, or evidence sequence | `tradingagents/graph/`, `tradingagents/agents/`, `ARCHITECTURE.md` |
| Vendor capability or A-share source behavior | `tradingagents/dataflows/`, `docs/operations/a-share-data-capabilities.md` |
| Web API, SSE, persistence, or Reader/Audit projection | `tradingagents/web/`, `frontend/src/api/contracts.ts`, relevant frontend consumers |
| React/TypeScript source | `frontend/AGENTS.md`; rebuild generated assets |
| Runtime, configuration, CLI, or workflow behavior | `README.md`, `ARCHITECTURE.md`, and focused docs |

Code schemas and validation are authoritative for machine contracts. Markdown
documents intent, ownership, compatibility, and navigation; do not duplicate
large schema definitions in prose.

## Local Boundaries

- Put credentials only in ignored local configuration such as `.env`,
  `.env.enterprise`, and `tradingagents.local.json`. Never commit values,
  copies, logs, fixtures, or documentation examples containing secrets.
- Default user data is outside this checkout under `~/.tradingagents/`.
  Treat caches, reports, run records, checkpoints, and local presets as user
  data; do not delete or rewrite them during routine development.
- `frontend/src/` is source. After changing it, run
  `npm --prefix frontend run build` and include the resulting tracked changes
  under `tradingagents/web/static/` in the same change.

## Finish Checklist

- Scope changes to the owning layer; retain existing uncommitted work.
- Start contract changes from their canonical Python or TypeScript schema and
  update every affected adapter, projection, and consumer.
- Run `python scripts/check_agent_docs.py` and the applicable Ruff, frontend
  install/typecheck/build checks; run pytest, Vitest, or Playwright only when
  their local-only scaffolding is present.
- Rebuild `tradingagents/web/static/` after frontend source changes.
- Update the current-state documentation surface when behavior, configuration,
  contract ownership, or operational workflow changed.
- Inspect `git diff --check` and `git status --short`; do not remove unrelated
  changes, local data, or generated assets belonging to another change.
