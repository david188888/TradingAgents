# ChatGPT connection recovery and sidebar

Status: Frozen Design

Do not use this document as evidence of current implementation behavior.
The user approved the design in chat on 2026-10-14 and requested implementation.

## Objective and invariants

Opening the workbench, returning from authentication, refreshing models and
selecting an account must each converge on the selected account's model catalog.
Local stored permission is not proof of a successful current catalog request.
Only the latest operation may publish UI state. Provider changes and unmounts
invalidate earlier work. Authentication happens only after a user's click on
an official OpenAI login action. Preserve account identity, catalog order,
explicit model selections, subscription billing boundaries and user data.

## Owning layers

- `chatgpt_errors.py` parses safe OAuth and API errors; accept both the OAuth
  string error shape and the API object shape, never raw upstream messages.
- The Web error envelope optionally includes the existing closed
  `ModelFailureDiagnostic`; frontend contracts mirror that addition.
- `useChatGPT` owns one sequential status → catalog operation with a revision
  guard. Account mutations and login completion explicitly run that sequence,
  including reauthentication of the same account. Model failures re-read local
  status to reflect credentials invalidated during refresh. No automatic
  retries of authentication, quota, permission or capability failures.
- Initial transient catalog/network failures may retry once; explicit retry
  remains available when the bounded recovery fails. This never sends inference.
- `useConfig` keeps submission blocked until both exact selected model IDs are
  in a usable current catalog. Re-selecting the same provider preserves choices.
- Shared model controls render identical recovery, models and language for
  single-company and batch creation. Empty selectors explain loading/failure.

## Interaction and appearance

Keep research input, model/account configuration and history in the left panel.
Use section headings, quiet dividers, consistent spacing and existing colors.
Show connection status once: checking, awaiting authorization, needs
reauthentication, catalog unavailable, usage paused, or models ready (catalog
availability does not prove inference permission). Provide the appropriate
primary recovery action; retain manual reauthentication in account options.
Account addition/logout and usage management remain accessible through native
details/summary. A login popup has a fallback link and cancellation control.
Errors appear once at their owning configuration section; the disabled submit
button references that explanation. Selects, long account labels and actions
must fit narrow viewports. Preserve focus visibility and reduced motion.

## Validation and delivery

Regression tests cover cold entry under StrictMode, same-account login,
same-account selection during loading, provider disable/re-enable, stale
responses after switching accounts, retry, authorization/quota failures,
model removal and popup fallback/cancellation. Python tests cover OAuth string
errors and secret-free Web diagnostics. Browser tests cover first entry,
reauthentication completion and single/batch consistency at desktop/narrow sizes.
Run scoped pytest/Vitest/Playwright, docs/Ruff, frontend install/typecheck/build,
and diff checks. Include rebuilt packaged assets and update current operations
documentation. Live consent requires the human; fixture results do not establish
that a real account has recovered or is eligible. No Git publication or service
restart is requested.
