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
components, and focused tests when the local-only test scaffolding is present.
Do not hide an incompatible API change with untyped casts or client-side key
translation.

## Commands

Public frontend checks start by installing the tracked lockfile dependencies:

```bash
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

The public fork does not track frontend test files/configuration or `e2e/`
scaffolding. When those local paths are present, their optional checks are:

```bash
npm --prefix frontend run test -- --run
npm --prefix frontend run test:e2e
```

`npm --prefix frontend run build` runs TypeScript build checks and Vite. Vite
writes directly to `../tradingagents/web/static/`, the tracked assets served by
the FastAPI package. Every `frontend/src/` change therefore requires that build
and inclusion of the resulting static-asset changes in the same change.

Use `npm --prefix frontend run dev` for local Vite development. The end-to-end
configuration starts its own Vite server on `127.0.0.1:4173` unless it can
reuse an existing local server.
