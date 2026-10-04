# DeepSeek task effort configuration

Status: Historical

Do not use this document as evidence of current implementation behavior.
See the [documentation index](../../README.md).

Implemented; publication state is recorded by the GitHub PR. See
[current configuration](../../operations/llm-reasoning.md) and
[validation](../../archive/reviews/2026-10-04-deepseek-task-effort-validation.md).

The user approved the fixed task allocation approach in the
[call-site audit](../../archive/reviews/2026-10-04-deepseek-effort-audit.md).
One model remains sufficient; effort changes reasoning allocation, not evidence
quality or independence. This change enables explicit overrides without lowering
any default or adding model phases. Live quality/cost comparison remains separate.

## Configuration and ownership

An optional `deepseek_task_efforts` mapping belongs to the effective runtime
configuration. Its keys are a finite, code-owned task registry in `llm_clients`;
values must be exactly `low`, `high`, or `max`. Unknown keys and invalid values
fail validation before graph/model execution. Nonempty overrides conflict with
explicit `deepseek_thinking=disabled` and are rejected rather than ignored.
For other providers this DeepSeek-specific mapping is inert.
Absent mapping and `{}` both mean inheritance; explicit null/non-mapping
values are invalid. Task keys and levels use exact lowercase strings.

Missing task entries inherit `deepseek_reasoning_effort`; missing mapping retains
the old behavior. Do not insert a new empty default key into old saved configs:
the existing semantic-config projection and fingerprint include overrides when
present and retain old identities when absent. Do not rewrite saved artifacts.
CLI JSON puts the mapping under `run`; programmatic requests (including
RunManager callers) put it directly in `effective_config`. The browser creation
form has no per-task control in this change; do not imply that its server reads
CLI JSON. There is no new UI selector or public request field.

## Actual task boundaries

- Native: `native.operating_quality`, `native.event_context`,
  `native.market_context`, `native.challenge`, `native.synthesis`.
- Classic: `classic.market`, `classic.social`, `classic.news`,
  `classic.fundamentals`, `classic.bull`, `classic.bear`,
  `classic.research_manager`.
- Legacy catalyst: `catalyst.catalyst_events`, `catalyst.operating_delivery`,
  `catalyst.market_reaction`, `catalyst.independent_refutation`,
  `catalyst.synthesis`. Retain the old profile and budgets.
- Auxiliary: `aux.news_cluster`, `aux.news_coverage`, `aux.news_sentiment`,
  `aux.news_deep_review`, `aux.context_compaction`, `aux.debate_summary`.

No task key for deterministic acquisition, metric calculation, source
qualification, verification, portfolio formatting or HTML/Markdown rendering.
Changing a task value does not enable an optional layer or invoke it again.

## Dispatch and recovery

`provider_llm_kwargs(config, task=...)` resolves native/legacy stage settings
without modifying the config. Classic graph setup gets separate task clients
only for explicit role overrides; compaction has its own client. Existing shared
global clients remain the fallback. All bound tools/structured recovery inherit
the chosen client and effort.

News helper calls use immutable `bind(reasoning_effort=...)` per actual task
on the existing client. Bind each from the original client, so classification,
coverage, clustering and deeper review do not inherit one another's overrides.
When any override policy is active, an unlisted auxiliary task explicitly binds
the global level (official default high if omitted), preventing accidental leak
from a caller-provided client. A malformed policy is never a successful
fallback. Native/catalyst runners deep-copy effective config at entry, before
identity construction and source collection, and callers also retain their own
copy. Classic graph construction freezes its config. External mutations cannot
change parallel dispatch settings; repair uses the same stage.
When a task policy is active, optional news deep-review cache keys also include
its resolved effort, so a max override cannot silently reuse a low conclusion.
Legacy cache keys remain unchanged without the optional policy.

Background/lazy classic debate summaries read the frozen snapshot's
`metadata.effective_config`, including the sanitized endpoint identity. They
never read current process config. Legacy snapshots lacking frozen config retain
their existing provider/model-only fallback. Empty native/catalyst debate
sources do not create a summary call. Optional summary failure remains nonfatal.

Existing dispatch authorization, uncertain-call accounting, retry limit,
deadline, cached proposals and request-config fingerprints remain authoritative.
No automatic low-to-high retries and no extra summary/assessment calls.

## Validation and delivery

Offline tests must check strict config validation, per-role/stage payloads,
global fallback, disabled mode, auxiliary isolation, CLI propagation, frozen
summary settings, native repairs, parallel invocation and checkpoint identity.
Run existing relevant native, config, graph, news, fingerprint and summary tests
without dotenv or the live paid DeepSeek test. Run Ruff and agent-doc checks;
update README, architecture/config operations docs and inspect whitespace/status.
Keep the managed worktree reviewable; do not commit, merge or push.
