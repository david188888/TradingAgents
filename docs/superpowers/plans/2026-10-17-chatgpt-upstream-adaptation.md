# ChatGPT upstream adaptation implementation plan

Status: Historical

Do not use this document as evidence of current implementation behavior.

Scope: the user-approved two adaptations in the [design](../specs/2026-10-17-chatgpt-upstream-adaptation-design.md).
Release package publishing and package-data fixes are excluded. Existing review
changes are retained. No Git publication, live auth/inference or service restart.

Local implementation and scoped offline verification completed on 2026-10-17;
see the [validation record](../../reviews/2026-10-17-chatgpt-upstream-adaptation-validation.md).

1. Complete context and design review. Preserve existing request ledger and
   account ownership; freeze compatibility before dispatch changes.
2. Add effort payload/config validation and a versioned checkpoint-policy marker.
   Propagate that marker through native calls and originating explanation jobs.
   Cover omission, explicit values, invalid input, repair/cache and old resume.
3. Save refresh metadata and per-account backoff under the existing lock. Cover
   minimum remaining validity, permanent vs transient errors, cross-instance
   serialization, token rotation, logout and cancellation.
4. Run focused offline pytest, then related native/public wiring/explanation suites.
   Run applicable Ruff, agent-doc and whitespace checks. Broaden only for failures
   or newly discovered integration risks.
5. Synchronize operations/architecture/READMEs and archive navigation. The root
   CHANGELOG is intentionally ignored; tracked changes belong in the review record.
   Record exact checks and limitations. Keep changes local and report the result.
