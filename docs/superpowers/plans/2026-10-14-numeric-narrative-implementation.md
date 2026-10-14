# Numeric narrative implementation

- **Status: Historical**
- **Do not use this document as evidence of current implementation behavior.**
- Design approved by the user on 2026-10-14: [numeric narrative design](../specs/2026-10-14-numeric-narrative-design.md).
- Current contracts remain in [the documentation index](../../README.md).
- Implemented locally on 2026-10-14; the current behavior is owned by the
  [numeric narrative contract](../../contracts/numeric-narrative.md).

## Delivery tasks

| Task | Estimate | Dependency | Acceptance |
| --- | --- | --- | --- |
| Typed numeric catalog and deterministic formatting | 5 points | Approved design | Exact values, qualification, periods, forecast/quote labels, conflicts and rounding pass offline tests; no source or model calls. |
| Restricted narrative envelope and independently replayable proof | 8 points | Catalog interface | Reject unbound/obfuscated quantities; validate per-item scope, plans and structural operands; compile before canonical IDs; bounded hypothesis isolation. |
| Native adapter/kernel/cache/publication integration | 8 points | Catalog/compiler | Fresh identities freeze policy; every invocation/cache/custom caller validates proof; existing repair/attempt budgets and fail-closed lifecycle remain. |
| Public record, focus and Reader/export qualification | 5 points | Main-chain proof | Public typed manifests reconstruct saved text; focus independent; legacy absent-field serialization and IDs unchanged. |
| End-to-end regression, documentation and generated frontend | 5 points | All integration | Whole output chain fixtures, historical compatibility, applicable Python/frontend checks, reviewed diffs and truthful limits. |

Subagents produced disjoint catalog/compiler and publication work. They then hit
the account quota; the main agent completed integration, adversarial tests and
final review without switching model/account or retrying failed subagents.
Existing ChatGPT/sidebar and prior audit changes are preserved. No Git publication,
live paid calls, service restart, history rewriting or workspace cleanup is part
of this authorization.

## Validation order

1. Pure catalog/compiler adversarial fixtures and exact formatting.
2. Adapter repair/isolation and cache integrity; then kernel dialogue, summary and focus.
3. Saved public record/Agent Reader/Markdown tamper and legacy-byte checks.
4. `python scripts/check_agent_docs.py`, applicable Ruff/pytest and frontend typecheck/build/tests; inspect `git diff --check` and status.

## Implementation receipt

The catalog, compiler, fresh identity marker, SDK/custom-caller admission,
bounded repair/isolation, durable cache recovery, typed record/focus attribution,
publication barrier, Reader/Agent projections and Markdown gates are implemented.
The TypeScript facade mirrors the new optional fields; generated frontend assets
were rebuilt with the existing ChatGPT/sidebar work present.

Adversarial offline fixtures cover source 18.4% versus fabricated 25%, Unicode
quantity hiding, exact threshold/operator bindings, unknown financial frequency,
future plan dates, forecast labels, missing operands, catalog overflow, receipt/
record tampering, successful repair replacement and failed-repair isolation,
whole-chain dialogue and inherited conditions, independent focus, readonly replay,
publication authorization/sequence, and a pinned pre-policy V7 record digest.
Expanded native regression tests retain old prompt, schema and workflow coverage.

Final checks use mocked sources/SDKs and deterministic callers; they establish no
real-provider protocol compliance, deployed behavior or improvement in economic
research quality.

- Expanded Python regression: 447 passed, one existing Starlette/httpx deprecation
  warning, in 209.52 seconds. This includes native source/record/model/repair,
  kernel/dialogue/focus/delivery, public Web wiring, Reader and isolation tests.
- Final catalog/compiler/dialogue/replay rerun: 51 passed in 62.13 seconds,
  including the added visible overflow limit (50 overlap the expanded suite).
  Subsequent Markdown and actual Web production regression: 35 passed, one
  existing deprecation warning, in 98.48 seconds. The added report-input tamper
  check verifies export identity binding and preservation of already-written
  report bytes; 34 tests overlap the expanded suite. Across these runs, 449
  distinct affected Python tests have passing evidence.
- Frontend lockfile install, typecheck and Vite build passed; the build retains
  the existing large-chunk advisory without changing its limit.
- Vitest: 371 passed in 51 files.
- Playwright: 10 passed for company-report delivery, question Reader and Reader
  quality, including actual local HTTP/SSE/publication navigation and accessibility.
  The first launch was blocked by the macOS sandbox before test code ran;
  approved sandbox escalation allowed the successful local browser run.
- Scoped Ruff, the agent documentation checker (137 Markdown files), and
  `git diff --check` passed; the final inventory preserves existing dirty state.

The successful-repair test found a stale original-candidate receipt selected after
a valid repair. The adapter now uses the accepted repair's own numeric receipt;
only failed/refused repair can select the original isolated candidate. Public
record validation also converts malformed binding shapes to closed validation
failure, and standalone inherited-field replay separates parent bindings from
metadata aliases.

## Knowledge closeout boundary

| Surface | State | Evidence / limit |
| --- | --- | --- |
| Code | changed-and-verified | Scoped offline tests and schema/cache/publication gates. |
| Runtime | pending | No live 8765 service observed; no restart, live provider run or deployment authorized. |
| Documentation | changed-and-verified | Numeric contract, unified contract, architecture, bilingual README and indexes aligned with code; dated designs remain historical. |
| Rules | verified-current | Root/package/frontend guides, existing Conda and scoped ownership followed; no rule change needed. |
| Memory | out-of-scope | Codex generated memory read-only; Hindsight not queried or modified. |
| Workspace | verified-current | Existing dirty work retained; seven existing worktrees inventoried without deletion. Local changes remain uncommitted. |

No changelog file exists in this checkout; this dated implementation receipt
records the change without inventing a release version. Plans/reviews and existing
worktrees are preserved for review rather than treated as automatically deletable.
