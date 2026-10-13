# Specialist reference isolation implementation

Status: Historical — Do not use this document as evidence of current implementation behavior.

Current behavior is documented in [Web evidence research](../../operations/evidence-research.md)
and the [documentation index](../../README.md).

Approved scope: the 2026-10-13 specialist-reference-isolation design. Changes
are local; Git publication and live research are outside this request.

1. Add closed typed hypothesis rejection codes and a shared validator in the
   owning proposal schema. Add an internal accepted-candidate envelope that
   binds proposal, original indices, rejection reasons and prompt digest.
2. Freeze the new specialist policy in fresh V7 identities; preserve absent
   policy for legacy resume and reject unknown policies.
3. In the SDK adapter persist a sanitized main candidate before the existing
   bounded repair, use it after known repair failure/refusal, and support
   read-only recovery without repeating a dispatched request.
4. Use shared validation and candidate metadata in kernel merge; preserve
   original indices, add rejection limitations and force partial status.
5. Update existing readable limitation labels and scoped operations docs.
6. Test actual mock-SDK adapter-to-kernel behavior and persisted Reader output,
   single repair accounting, policy/cache compatibility, malformed responses,
   all-invalid results, control failures and recovery. Run affected pytest
   suites, Ruff, agent-doc validation and git diff checks.
