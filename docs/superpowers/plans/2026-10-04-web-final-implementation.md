# Web final implementation and acceptance

Status: Local functional implementation and validation complete; human reading and comparative quality acceptance remain open.

This is a delivery checklist; current-state contracts remain code-owned.

Approved scope: [Web design](../specs/2026-10-04-web-final-design.md), option A;
CLI analysis excluded. Base checkout: `9abb840`.

1. Freeze Web native default, batch propagation and retired creation/retry
   semantics in canonical API requests and client facade; preserve saved recovery.
2. Replace creation controls/request builder with native Web fields and existing
   model settings; migrate batch builder; add focused lifecycle/contract checks.
3. Add bounded qualified valuation evidence and deterministic saved context;
   version source topology; test failures, dates, identity, arithmetic and replay.
4. Complete Reader hierarchy, saved-content citation interaction and valuation
   rendering; build tracked assets and test three scopes and limited results.
5. Repair the local PDF dependency in an isolated runtime if needed; run one
   bounded 600803 live company study, inspect records/calculations and actual UI.
6. Run required checks, reconcile durable current-state docs (Web support and
   CLI maintenance boundary), record remaining human/quality acceptance honestly,
   and present actual HTML/browser output. No remote publication.

Steps 1–6 are implemented and verified locally. Full Python regression passed
3,149 tests (four live Wind tests skipped; one live DeepSeek class deselected);
315 Vitest tests, 19 Playwright scenarios, typecheck/build, Ruff and agent-doc
checks passed. Tracked SPA assets are rebuilt. The delivered actual Web/HTML
and remaining human/quality checks are recorded in the
[dated acceptance review](../../reviews/2026-10-04-web-final-acceptance.md).

The two fresh 600803 runs consumed 10 SDK attempts. The user-approved frozen
validation used exactly six more, with zero new source attempts. It published
`complete / LOW_CONFIDENCE`, three conditional dimensions, three unresolved
challenges and no independently executed verification. This establishes repaired
pipeline wiring and readable limited output, not completed research quality.
No additional paid work is authorized by this checklist. On 2026-10-05 the user
separately authorized major GitHub publication; see the
[v3.0.0 release notes](../../reviews/2026-10-05-v3-release-notes.md). This changes
publication scope, not the remaining research-quality acceptance.
