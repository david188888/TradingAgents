# Native model retry and official PDF recovery

Status: Frozen Design

Do not use this document as evidence of current implementation behavior.
Implemented scope and remaining limits are recorded in the
[600418 investigation](../../reviews/2026-10-11-600418-research-investigation.md).
Current retry behavior belongs in [observability and replay](../../operations/observability-replay.md#原生模型有限网络重试).

User-approved scope: retry a failed model request up to three times after the
initial request, waiting 2, 5, then 10 seconds. Complete declared dependencies
in the `tradingagents` Conda environment and fix the confirmed 600418 PDF
numeric-column parsing defect. Do not rewrite historical user run records.

## Request boundary

Use adapter-owned retries rather than SDK automatic retries: each extra
request reserves and dispatches `network_retry` in the durable ledger and
counts toward `model_attempts`. Preserve the existing run-wide limits of three
network retries and twelve total model attempts; therefore a later logical
call can stop before its third retry when shared quota is exhausted.

Only explicit transient failures qualify: connection/timeout exceptions,
HTTP 408/429 and HTTP 5xx, excluding recognized quota, authorization and
configuration errors. JSON/schema errors retain the existing one-repair
path. The optional V6 focus call retains its no-retry policy. SDK retries
remain disabled. Retry waits release global request slots and check run
cancellation/deadline. A crash or unknown prior dispatch never authorizes a
repeated request during recovery.

Freeze the retry policy in fresh run identity. Historical identities without
the policy retain their existing behavior. Record redacted per-attempt
diagnostics and retry authorization flags; include retry requests in Reader
SDK totals and role counts without changing the public DTO schema.

The existing single structured-repair request may receive transient retries;
each extra request uses the shared network quota, retaining its repair origin
in the authorization key. Reader counts main retries under `sdk_main` and
repair retries under `sdk_repair`. Only actual dispatch authorizations count.
Each request owns its measured tokens exactly once: final retry usage belongs
to its retry reservation, never also to the original MAIN/repair reservation.
Failed dispatched retries settle with unknown usage. Reserved retries cancelled
before dispatch are released; persistence failure stops all further requests.
Resume reconstructs exact identity from the saved presence/value of the policy;
an absent policy stays absent and an unrecognized policy fails compatibility.

## PDF boundary

Reject malformed numeric cell segmentation rather than guessing where glued
columns split. Retain qualified consolidated-statement rows. Check the saved
600418 half-year PDF offline: revenue must resolve to 22,130,027,990.11 and
19,359,903,999.02 without a false cross-section conflict.

## Validation

Mock requests and waits to verify transient success/exhaustion, permanent
errors, cancellation, deadlines, durable accounting, recovery, repair and
Reader counts. Verify the real saved PDF without paid model calls. Run scoped
Python tests, Ruff, documentation checks and `git diff --check`. Preserve
concurrent ChatGPT subscription changes and distinguish source verification
from the currently running service.
