# ChatGPT upstream v0.7.0 selective adaptation

Status: Frozen Design

Do not use this document as evidence of current implementation behavior.

The user approved the review's ChatGPT adaptations on 2026-10-17 and explicitly
excluded Release installation-package publishing. The prior review remains a
historical snapshot; current ownership is in [ChatGPT operations](../../operations/chatgpt-subscription.md).

## Scope and alternatives

Implement explicit ChatGPT reasoning-effort delivery and bounded OAuth refresh
resilience. Keep the existing dedicated client, account registry, official route,
quota controls, request ledger and completed-stream acceptance.

Three approaches were considered:

1. Adapt the two gaps in the existing modules (selected): small surface, preserves
   account isolation and deterministic execution boundaries.
2. Replace the provider with upstream's SDK adapter: unnecessary migration of
   credential ownership, cancellation and request accounting.
3. Forward effort without a saved policy: smaller patch, but silently changes
   requests resumed from historical checkpoints; rejected.

No wheel/package-data changes, publication workflow, model-list reordering,
additional login UI, provider tiers, automatic update checks, default-effort change,
paid inference, credential migration, Git publication or service restart.
Optional refresh ID-token revalidation is not included: that would require a
separate rotation-safe identity-validation design, beyond timing/fault resilience.

## Reasoning and historical compatibility

- `provider_llm_kwargs` forwards `openai_reasoning_effort` for ChatGPT as it does
  for OpenAI. The dedicated client encodes an explicit value as
  `reasoning: {effort: value}` in Responses JSON; omission sends no reasoning field.
- Accept the documented union `none/minimal/low/medium/high/xhigh/max` as exact
  string values. This is syntactic validation, not a capability claim for any
  model. Unsupported model-specific settings fail without auto-substitution.
- Freeze `chatgpt_request_policy = siwc-reasoning-v1` in fresh ChatGPT native
  checkpoint identities. Existing effective configuration already preserves the
  selected effort; the additive marker distinguishes old request semantics.
- `native_identity` and resume validation must reproduce both marked and unmarked
  identities exactly. Unknown markers and changed frozen effort reject resume.
- NativeModelCaller reads the saved marker. Shared request invocation forwards
  effort only for the known marker; unmarked historical callers retain omission.
  Direct ChatGPTClient construction honors an explicit effort argument.
- New native runs get the marker; retries creating a new run may get the new
  policy while retaining their inherited explicit configuration. Same-run resume
  never upgrades. The snapshot's original effective configuration is not rewritten.
- Report-explanation jobs use the originating checkpoint's marker, including
  explicit retries of old jobs. Their existing frozen-config hash and artifact
  contracts stay intact. Reads never generate work.
- Validate marked explicit effort before source collection. Preserve SDK retry=0,
  request dispatch barriers, deadlines, budget and bounded repair semantics.

## Refresh timing and transient failures

- Preserve the current 60-second near-expiry refresh margin.
- Save optional `earliest_refresh_at` at login and successful refresh. Only finite,
  non-negative numeric timestamps are usable; absent/malformed optional metadata
  is treated as absent. Expired access tokens may refresh despite a later earliest
  time; no expired token may be returned.
- Before expiry, honor a future earliest time. A retained token must have more
  than five seconds remaining at the instant it is returned. Otherwise return a
  safe retry-later diagnostic without sleeping or refreshing early.
- After a transport timeout/connection failure or generic HTTP 408/429/5xx,
  atomically save a per-registration next-refresh time 60 seconds later. Other
  processes see the same backoff. A still-valid token may serve during it.
- The closed transient whitelist requires category=request_failed and either
  transport_timeout/transport_connection_error, or those HTTP statuses with code
  request_failed/server_error/internal_server_error/temporarily_unavailable/
  rate_limit_exceeded (or no code). Semantic authorization/quota errors never
  become transient just because their HTTP status is 429 or 5xx.
- During backoff, an insufficiently valid/expired token yields the closed
  `refresh_temporarily_unavailable` retry-later diagnostic, with no HTTP dispatch.
  This diagnostic must not trigger native automatic inference retries.
- Authorization, identity, permission, subscription-usage and permanent quota
  failures never reuse a token through this fallback. Existing invalid_grant /
  invalid_client token clearing remains. Arbitrary upstream prose is never saved.
- Successful refresh atomically saves the rotated token, updates earliest time,
  and clears refresh backoff. Reauthorization and logout clear stale backoff.
- Keep refresh/logout serialization and session-generation checks. Cancellation
  and deadline checks still run before inference dispatch, including after a
  refresh worker finishes. No new background refresh thread or inference request.

## Validation and delivery

Use the existing tradingagents Conda environment, synthetic credentials, local
callback fixtures, MockTransport and injected clocks. No user auth/run data.

Required coverage:

- Explicit/omitted/invalid effort at client and shared invocation boundaries;
  request payload, usage and terminal-event behavior remain correct.
- Fresh identity vs historical identity; changed/unknown marker and effort refuse
  resume; cached output and repair keep frozen semantics; supplementary jobs use
  the originating policy.
- earliest timestamp saving, future/absent/malformed cases, expiry override,
  temporary failure fallback, fallback validity recheck, per-account and
  cross-instance backoff, post-backoff success, expired-token refusal, permanent
  errors, concurrent rotation/logout and cancellation before inference dispatch.
- Applicable pytest suites, Ruff, agent-doc checker and whitespace checks.

Update operations, architecture, reasoning docs, both READMEs and the tracked change record as
appropriate, and link design/verification through archive navigation. Preserve the
original review and annotate the subsequent user decision. Tests prove parameter,
recovery and failure contracts; no claim of real-account availability or better
investment outcomes without separate live authorization and evidence.
