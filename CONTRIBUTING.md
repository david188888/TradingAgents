# Contributing

TradingAgents maintains a local A-share Web research workbench. Preserve evidence provenance,
saved-run compatibility and unrelated work. Start with [architecture](ARCHITECTURE.md) and the
[scoped Agent guides](AGENTS.md) for files being changed.

## Setup

```bash
conda activate tradingagents
python -m pip install -e ".[china,web,dev]" --index-url https://pypi.org/simple
npm --prefix frontend ci
```

Reuse the existing Conda environment; only create it if absent. Copy `.env.example` to `.env` on first
setup. The legacy CLI may read `tradingagents.local.json`; Web does not. Credentials and runtime data
must stay out of commits. Node is for frontend development/builds, not installed-Web runtime.

## Change routing

| Change | Start here |
| --- | --- |
| Request/result, cancellation, execution identity | `tradingagents/execution/models.py`, `native_runner.py`, `runtime/` |
| Research artifacts, qualification, calculations | `tradingagents/agents/schemas/`, `research/`, `dataflows/` |
| Role sequence or scope | `tradingagents/graph/native_research.py`, `research/native_policy.py` |
| Web/Reader/SSE | `tradingagents/web/` and `frontend/src/api/contracts.ts`, then consumers |
| Browser interaction/state | `frontend/AGENTS.md`, API transport, stores/hooks, components |

Canonical schemas own fields and validation. Update producers, persistence/replay, projections and
consumers together; do not derive a new machine contract from Markdown or a rendered report.
Keep historical identities/prompts and absent-field serialization compatible where supported.

## Scoped Validation

Choose the smallest set of checks that covers the changed behavior and its consumers.
Full pytest, all frontend tests and all E2E tests are not required after every optimization.

| Change | Default validation |
| --- | --- |
| Documentation or comments only | `python scripts/check_agent_docs.py` for Markdown changes; `git diff --check`. No application tests; the frontend source build rule still applies if `frontend/src/` changes. |
| Local Python behavior | Ruff on changed Python files, including tests, plus relevant pytest files or test cases. |
| Frontend source | Relevant Vitest files for affected behavior plus one `npm --prefix frontend run build`. |
| Persistence, recovery, API contracts or the research pipeline | Expand regression to affected producers and consumers; run the relevant Playwright specs when a complete browser flow is affected. |
| Version release or broad shared changes | Broader offline regression for affected layers; use full suites when the impact spans the layer. GitHub publication alone does not require a full run. |

Run `git diff --check` for every change. For a local fix, select explicit test paths or cases,
for example `python -m pytest tests/test_search_budget.py` or
`npm --prefix frontend run test -- --run src/hooks/useRunStream.test.ts`.
Add or adjust tests for meaningful behavior changes and regression gaps; small edits do not
automatically need new tests. Preserve existing tests unless their removal is separately agreed.

Reuse passing checks while the relevant code, tests, fixtures, configuration, dependencies and
environment remain unchanged. Commit, push or PR creation alone does not invalidate them.
After a broader run passes, do not rerun its covered subsets; after a change or failure, rerun
the checks it affects. Record the scope and result in the PR rather than repeating the run.

Run `npm --prefix frontend ci` for first setup, dependency/lockfile changes or an incomplete install,
not for every frontend edit. Build already runs TypeScript checks and writes to tracked
`tradingagents/web/static/`; include generated changes in the same change. Standalone `typecheck`
is useful for quick feedback during editing, but is not an additional delivery requirement.
For Playwright, install Chromium once from `frontend/` with `npx playwright install chromium`,
build the SPA, and set `TRADINGAGENTS_E2E_PYTHON` when the fixture server's `python` would use
another environment. Select affected specs; see the [frontend guide](frontend/AGENTS.md).

`python -m pytest -m unit` and `python -m pytest -m 'not integration'` select different subsets;
many tests have no level marker, and neither selection guarantees offline execution. Inspect
selected tests before broader runs. Live model/provider checks require explicit authorization;
the real DeepSeek integration test also requires `TRADINGAGENTS_RUN_LIVE_TESTS=1` and a real key.
Report exact suites, exclusions and failures rather than calling a scoped run “all tests passed”.

## Documentation Impact

Maintain four core reader/developer pages: the README pair, architecture, Web operations and this
guide. `docs/README.md` is short navigation; technical references are optional. Put each current fact
in its owning page and link to it elsewhere. Explain goals, responsibilities, critical boundaries and
how to find the canonical code; do not duplicate full schema fields or per-version implementation logs.

Keep Chinese/English READMEs aligned. Update the owner when behavior/configuration changes; otherwise
state `No documentation impact` in the PR. New historical reviews/plans are not required for routine
changes: keep temporary execution notes outside maintained docs, and retain only durable decisions or
material verification evidence. Existing archives stay available and are not current instructions.
Old document paths may remain short pointers so saved links keep working.

## PR Hygiene

Do not commit secrets, user run stores, caches, private datasets or unrelated changes. Use the existing
Ruff pre-commit gate without bypassing it. No GitHub Actions workflows are tracked in this fork;
verify remote requirements when publishing, and do not treat absent checks as successful CI.

When Git publication is authorized, use branch → PR → merge after applicable local checks and required
remote checks/reviews pass. Stop for material scope uncertainty, conflicts, failed/pending checks or
missing required review. No separate merge confirmation is needed within that authorized scope.
