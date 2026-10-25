# Research contract sources

Status: Current

The [research contract](research-record.md) is the maintained explanation of evidence, calculations,
search limits, publication and reading. Full machine definitions remain in code:

| Change | Canonical source |
| --- | --- |
| Input/result and profile identity | [execution/models.py](../../tradingagents/execution/models.py), [native_runner.py](../../tradingagents/execution/native_runner.py) |
| Public record, proposals, assessment, numeric and search types | [agents/schemas](../../tradingagents/agents/schemas/) |
| Source/number qualification and pure domain validation | [research](../../tradingagents/research/), [dataflows](../../tradingagents/dataflows/) |
| Durable runs, events, budgets and publication | [runtime](../../tradingagents/runtime/), [execution](../../tradingagents/execution/) |
| HTTP and read-only projections | [web](../../tradingagents/web/) models, routes and qualification modules |
| Browser wire facade | [frontend/src/api/contracts.ts](../../frontend/src/api/contracts.ts) |

Update every affected producer, persistence/replay path and consumer after changing the canonical
model; preserve supported saved identities. Diagnostics and measurement are explained in
[observability/replay](../operations/observability-replay.md). Older focused URLs remain navigation
pointers, not parallel definitions. [Documentation index](../README.md) provides the short reading path.

<!-- Compatibility anchors for existing section links. -->
<a id="canonical-sources"></a>
<a id="change-propagation"></a>
<a id="compatibility-rules"></a>
<a id="contract-index"></a>
