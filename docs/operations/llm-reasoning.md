# Model reasoning configuration

Status: Current

## Official DeepSeek API

The `deepseek` provider uses Chat Completions at `https://api.deepseek.com`
unless the effective configuration overrides the endpoint. The official
V4.1 Flash model ID is `deepseek-flash`; it is available in both quick and
deep model selectors and uses the DeepSeek capability adapter. Existing
`deepseek-v4-flash` configurations remain accepted. Repository model defaults
and saved model IDs are not rewritten by this compatibility update.

As verified on 2026-10-04, the official service temporarily routes the old
Flash ID to V4.1 Flash. This is provider behavior, not a pinned historical
model version. See the [official change log](https://api-docs.deepseek.com/updates/).

The existing settings are:

| Setting | Behavior |
| --- | --- |
| `deepseek_thinking` | `enabled` by default; `disabled` is sent explicitly to the API. |
| `deepseek_reasoning_effort` | Global `high` default. `low`, `high` and `max` are distinct official levels; compatibility values `medium` and `xhigh` map to `high` at the service. |
| `llm_max_tokens` | Optional output ceiling. `None` leaves the provider ceiling in effect; it is not a report-length target or a fixed cost. |

The environment equivalents are `TRADINGAGENTS_DEEPSEEK_THINKING`,
`TRADINGAGENTS_DEEPSEEK_REASONING_EFFORT` and `TRADINGAGENTS_LLM_MAX_TOKENS`.
An explicit disabled mode suppresses the retained effort setting, including
when constructing the provider client directly: a non-none effort could
otherwise enable thinking. Thinking-mode temperature is omitted because it
has no effect. No additional sampling controls are introduced.

The client preserves prior `reasoning_content` for tool conversations. Thinking
mode binds the structured-output schema without forcing a particular function;
non-thinking mode permits that choice. JSON/schema and evidence validation
remain necessary. See [official thinking controls](https://api-docs.deepseek.com/guides/thinking_mode/)
and [Chat Completions restrictions](https://api-docs.deepseek.com/api/create-chat-completion/).

## Optional task overrides

`deepseek_task_efforts` is an optional mapping in effective configuration.
Each entry overrides the global effort for one actual call task. Missing entries
inherit `deepseek_reasoning_effort`; with an active policy and no global level,
they use the official default `high`. Without a policy, legacy behavior is
retained. Both `{}` and omission mean no override; null/non-mapping values,
unknown task keys, and levels other than exact `low / high / max` fail validation.
A nonempty policy with explicit disabled thinking is rejected for DeepSeek.
The setting is inert for other providers.

The finite code-owned registry is `llm_clients/task_effort.py`:

| Tasks | Boundary and initial guidance |
| --- | --- |
| `native.operating_quality`, `native.event_context` | Operating mechanisms and event implementation: retain `high`. |
| `native.market_context` | Market interpretation: retain `high`; candidate for a later low comparison. |
| `native.challenge`, `native.synthesis` | Alternatives, unresolved risks and synthesis: retain `high`; explicit `max` can be evaluated for complex cases. |
| `classic.market`, `classic.social`, `classic.news`, `classic.fundamentals` | Four analyst tasks. Market/social are later low candidates; news/fundamentals are substantive analysis. |
| `classic.bull`, `classic.bear`, `classic.research_manager` | Causal arguments and final synthesis: retain `high`. |
| `catalyst.catalyst_events`, `catalyst.operating_delivery`, `catalyst.market_reaction`, `catalyst.independent_refutation`, `catalyst.synthesis` | Existing legacy stages; preserve global behavior unless explicitly configured. |
| `aux.news_cluster`, `aux.news_coverage` | Event clustering and missing-coverage queries. Low comparison candidates; clustering affects evidence credibility, so check false merges and missed risks. |
| `aux.news_sentiment` | Compact news classification, only when the existing optional Layer 1 is enabled; early low comparison candidate. |
| `aux.news_deep_review` | Existing optional Layer 2 review; retain `high`. |
| `aux.context_compaction`, `aux.debate_summary` | Public context compression and classic reading index; early low comparison candidates that must preserve caveats and source attribution. |

These are review recommendations, not measured quality/cost results. No
task-specific defaults are inserted and no local user preset is rewritten.
The default global effort remains `high`. Deterministic data collection, metric
calculation, source qualification, verification and report rendering have no
effort setting. Effort changes do not enable optional stages or add calls.

For the CLI, place overrides under `run` in the ignored local JSON configuration.
This is an optional comparison example, not an automatically enabled preset:

```json
{
  "run": {
    "deepseek_thinking": "enabled",
    "deepseek_reasoning_effort": "high",
    "deepseek_task_efforts": {
      "aux.context_compaction": "low",
      "aux.debate_summary": "low",
      "aux.news_sentiment": "low"
    }
  }
}
```

CLI selections forward both global DeepSeek controls and the task mapping.
Programmatic `AnalysisRequest`/RunManager callers put the mapping directly in
`effective_config`. The browser creation form has no per-task selector and its
server does not read this CLI JSON. No environment mapping for task policies is
introduced. Do not infer that selecting quick/deep model IDs selects effort.

## Isolation, persistence and repair

`provider_llm_kwargs(config, task=...)` resolves native and legacy stages.
Synthesis still selects the deep model ID; other stages select the quick ID.
Native/catalyst runners freeze config before source collection and identity
construction. Classic roles with explicit overrides use separate clients;
news helpers bind settings per task on the original client. Shared clients and
configuration are not mutated. Unlisted tasks inherit the global level even
when another auxiliary task has an override.

Structural repair inherits the original task's effort. Native/legacy repair
remains charged to the existing durable budget, SDK retries stay disabled and
timeout uses remaining run time. There is no automatic effort escalation. With
an active task policy, optional news deep-review cache keys include resolved
effort; changing its effort cannot reuse a conclusion from another level.

Effective configuration and checkpoint identities include the mapping when
present. Changing it makes a checkpoint incompatible; resume retains saved
settings and consumed budget. Missing policy keys are not added to old saved
configurations, and saved result artifacts are not rewritten.

Optional classic debate summaries use the frozen snapshot's effective settings
and endpoint. Older snapshots without effective settings retain provider/model
fallback. A malformed frozen policy does not dispatch; summary failure remains
nonfatal. Existing background/lazy generation triggers and cache behavior remain.
Native completion skips background debate-summary scheduling; native
Reader/Markdown render saved research records. The generic view cache can enter
the summary helper, which returns without a model call when no debate rounds exist.

For the original call-site rationale and future quality comparisons, see the
[effort audit](../archive/reviews/2026-10-04-deepseek-effort-audit.md) and
[implementation design](../archive/designs/2026-10-04-deepseek-task-effort-design.md).
Offline parameter/schema/budget tests do not establish investment-analysis
accuracy, actual savings, or the benefit of `max`. Keep those claims unverified
until bounded comparisons are authorized and measured.
The [validation record](../archive/reviews/2026-10-04-deepseek-task-effort-validation.md)
also covers one live wiring case and browser checks; it is not a quality comparison.
