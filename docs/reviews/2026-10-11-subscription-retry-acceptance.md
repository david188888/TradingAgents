# Subscription, native retry and Reader closeout

Status: Historical

Date: 2026-10-11

Do not use this document as evidence of current implementation behavior.
Current contracts belong in [subscription operations](../operations/chatgpt-subscription.md),
[observability and replay](../operations/observability-replay.md), and the
[Reader architecture](../architecture/research-reader.md).

## Delivered scope

The combined change adds official ChatGPT OAuth, protected local registrations,
dynamic model catalogs, single/batch account binding and completed Responses
stream handling. It also adds durable native transient retries and safe model
diagnostics, rejects glued official PDF money cells without guessing a split,
and makes in-progress Agent review scroll/focus and return focus correctly.
Historical records and unknown prior model dispatches are not replayed or rewritten.

On 2026-10-11 the user explicitly approved generic subscription HTTP 408/429/5xx
retries under the shared native policy. Recognized quota, permission, capability,
protocol and incomplete-stream failures retain no retry. Optional focus retains
one call. The Responses client itself issues one request per invocation.

Web tests previously constructed default authentication against a contributor's
real account directory. The shared fixture now redirects default auth instances
to a temporary directory while retaining explicit test roots, preventing account
reads and permission mutations during contributor tests.

## Verification in the service's Conda environment

- Scoped Python regression: 886 passed across Web, native, minimum-evidence,
  disclosure, subscription and numeric-cell suites after auth isolation.
- Following the explicit subscription retry decision, `test_native_retry.py`:
  33 passed, including seven HTTP/permanent-error intersection cases.
- Frontend: 48 Vitest files / 336 tests passed; 24 Playwright tests passed,
  including desktop/mobile reading, subscription selectors and keyboard focus.
- Dependency install, TypeScript checks, generated SPA build, Ruff, Agent docs
  links and `git diff --check` passed. Chromium required sandbox-external launch
  because the restricted macOS environment denied Mach-port registration.
- The actual 8000 workbench served exactly the built index and both asset files;
  its subscription status retained one authorized registration. No active runs
  existed during inspection. No new formal research or paid inference was started.
- The existing 600418 record API was preserved. Earlier PDF and frozen-call
  evidence remains in the [dated investigation](2026-10-11-600418-research-investigation.md);
  it is not a fresh complete subscription company-research acceptance.

## Limits and retained warnings

This is engineering acceptance, not research accuracy or predictive validation.
Full company research through ChatGPT subscription remains unverified. Automotive
monthly production/sales admission, negative-base cashflow risk definitions and
synthesis-input deduplication were not changed.

The existing Conda environment reports mootdx's httpx/tenacity declaration
conflicts; no dependency downgrades were applied. Frontend npm audit reports
18 advisories (4 moderate, 12 high, 2 critical), and Vite reports a chunk above
500 kB. Dependency/security remediation is separate work. A Starlette test-client
deprecation warning remains. GitHub checks/reviews and merge state must be verified
from the PR, separately from these local results. No new release/tag or homepage
deployment is implied by this change.
