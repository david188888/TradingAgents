# Compatibility and legacy integrations

Status: Current

This page describes supported legacy reading/recovery and retained public callers. It does not enable
new old-profile Web studies. New work follows [Web operations](evidence-research.md) and the
[current research contract](../contracts/research-record.md).

## Saved workflow recovery

Classic and `catalyst_v1` creation/retry return 410; historical native catalyst/holding modes cannot be
newly created/retried and return 422. Compatible interrupted runs can resume under their original
profile, mode, source policy, prompt/kernel versions, request/configuration and spent budget.
Saved valid results replay; uncertain dispatched calls stay spent. Recovery is not an upgrade.

The retained catalyst runner freezes its own evidence and executes three specialists, independent
refutation and synthesis under the saved policy. Its case/record publication retains the original
lifecycle barrier. Classic follows `TradingAgentsGraph → AnalysisRunner → LangGraph`, with Evidence
Steward and bull/bear research convergence. Trader/risk-debator execution was retired; older state or
metadata names do not prove those nodes still execute. CLI analysis is outside continued maintenance.

Reading a missing old artifact does not manufacture it. Historical source limits, unavailable
quantitative metrics and converted model dispositions stay explicit; conversion is not executed
verification. Unknown versions/integrity conflicts refuse qualification or recovery rather than
silently adopting the current collector. Canonical routing/compatibility lives in
[execution](../../tradingagents/execution/), [graph](../../tradingagents/graph/) and
[Reader policy](../../tradingagents/web/native_reader_versions.py).

## Analyst presets

YAML presets configure the four classic analysts only. Native roles/prompts/methodology mapping are
code-owned. Presets cannot add tools, graph edges or downstream research roles.
Built-ins are in `tradingagents/presets/`; a valid same-ID file in `~/.tradingagents/presets/` overrides
one without modifying package files. Allowed keys are `id`, `label`, `analysts`; analyst values are
unique members of `market`, `social`, `news`, `fundamentals` in the requested order.

```bash
tradingagents inspect-preset ~/.tradingagents/presets/news-first.yaml
```

Inspection uses [presets.py](../../tradingagents/presets.py) without models; invalid YAML exits 2.
Historical convergence metadata includes retired names, not actual topology. Analyst order is part of
request/resume identity. The executable graph, not YAML or Markdown, owns downstream routing.

## External classic package consumption

Classic runs may publish `research-case-v2` plus `research-package-v1`. External Agents resolve one
confirmed run/ticker, read `/api/runs/{id}/reader/package`, validate its version and bind each answer
to `run_id`, canonical `package_sha256` and relevant stable entity/evidence IDs. Use selected Reader,
Companion and evidence-ref routes to inspect public material, not private run-file scans or array positions.

[research_package.py](../../tradingagents/research/research_package.py) owns the package and
[public_hash.py](../../tradingagents/research/public_hash.py) its public projection/hash. Unknown
observations remain unknown; source prose does not upgrade missing package facts. Conversation state
belongs to the external Agent, not a local conversation API. The interoperability Skill is statically
mapped to the classic Research Manager and is not a native research stage.

Native V8 publishes `research-record-v2` through `/reader/record`, without a paired classic case or
package. Historical native workflows use V1. Missing `/reader/package` is therefore not a native
execution failure. Compatibility metrics validate each operand and require the exact prior-year
reporting period for YoY. Unknown periods, TTM/cumulative basis and unproven ROE equity endpoints
remain unavailable; package presence alone does not establish financial comparability.

## Wind

The classic vendor path can use the pinned Wind CLI for adjusted prices, registered indices,
EDB search/series and provider-reported risk. Configure `WIND_API_KEY` and, if necessary,
`WIND_CLI_PATH`. Native evidence collection does not use Wind, even when `wind_enabled=true`.
Provider/transport ownership is [wind_provider.py](../../tradingagents/dataflows/wind_provider.py);
[default_config.py](../../tradingagents/default_config.py) and
[registry.py](../../tradingagents/dataflows/registry.py) own the pin, settings and actual fallback chains.

Wind requests remain serialized by default. Explicit index identity avoids guessing an equity from
a bare numeric code; `.SS`→`.SH` conversion requires known Shanghai identity. Missing/INVALID is not
zero. EDB allowlist enforcement is optional configuration, not permission to treat every discovered
code as approved. Snapshot/history fallback differs from profile/fundamental capability support.

Authentication, balance and quota failures require explicit recovery or their confirmed reset;
transient errors may follow bounded retry/fallback. No-results does not prove no event. Warnings
with usable data remain partial. Wind fundamental/news/document/fund/bond/analytics tools are not
implicitly added to the current default research route. Historical design scope is not delivery.

## Extending compatibility

Keep public facade imports and version-specific serialization until their retirement policy changes.
A static search finding no internal caller is not enough to delete a public helper or recovery branch.
Change the owning canonical code, consumers and focused historical fixtures together; do not rewrite
user runs, infer new permissions from old plans or re-enable retired Web entry points through docs.

<!-- Compatibility anchors for existing section links. -->
<a id="budget-cancellation-and-recovery"></a>
<a id="explicit-catalyst-research-trials"></a>
<a id="historical-trial-setup"></a>
<a id="read-a-result"></a>
<a id="sources-and-qualification"></a>
