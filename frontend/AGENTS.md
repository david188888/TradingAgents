# `frontend/` Workbench Guide

This directory contains the React 18 and TypeScript source for the local
workbench. Repository-wide setup and generated-output rules live in
[../AGENTS.md](../AGENTS.md).

## Ownership

- `src/api/contracts.ts` is the client contract facade. It mirrors the
  server's wire format without renaming keys; the canonical backend sources
  are identified in that file's header.
- `src/api/` owns HTTP and SSE transport behavior.
- `src/state/` owns per-run store, reducer, selectors, and state model.
- `src/hooks/` composes transport and state for UI consumers.
- `src/components/` owns presentational and workflow surfaces; keep data
  fetching and cross-run state out of leaf components when an existing hook or
  store boundary applies.
- `src/styles/` owns global tokens and workbench styling.

When an API shape changes, update the backend's canonical model/adapter first,
then `src/api/contracts.ts`, transport code, reducers/hooks, consuming
components, and focused tests when the tracked test scaffolding is present.
Do not hide an incompatible API change with untyped casts or client-side key
translation.

## Commands

Follow the [scoped validation matrix](../CONTRIBUTING.md#scoped-validation).
Install lockfile dependencies with `npm --prefix frontend ci` for first setup,
dependency changes or an incomplete install. For a localized behavior change,
select the relevant tracked Vitest files, for example:

```bash
npm --prefix frontend run test -- --run src/hooks/useRunStream.test.ts
npm --prefix frontend run build
```

`npm --prefix frontend run build` runs TypeScript build checks and Vite. Vite
writes directly to `../tradingagents/web/static/`, the tracked assets served by
the FastAPI package. Every `frontend/src/` change therefore requires that build
and inclusion of the resulting static-asset changes in the same change.
Standalone `typecheck` is optional feedback while editing, not an extra check
before the same build. Documentation-only changes do not require a build.

Run selected Playwright specs with `npm --prefix frontend run test:e2e -- <spec>`
when a complete browser flow is affected. Use broader suites for shared behavior
changes or version releases, not every component edit. Reuse passing checks while
their inputs remain unchanged; publication alone does not require another run.

Use `npm --prefix frontend run dev` for local Vite development. The end-to-end
configuration starts the Python fixture server on `127.0.0.1:4173`, serving
the built SPA, synthetic native 600803 runs and legacy Reader records. Build before running it;
it can reuse an existing local server.
