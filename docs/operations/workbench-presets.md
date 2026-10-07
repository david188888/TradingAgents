# Legacy analyst presets

- **Status: Current**

YAML presets remain available to the legacy CLI and preset inspection tooling
for the four classic analyst roles. The maintained Web form creates only
`evidence_v1` research with fixed native roles and has no preset selector.
Presets cannot change native roles, prompts or research-methodology mapping.
A classic preset can enable a subset and choose execution order; it cannot add
tools, agents, prompts, retries or graph edges.

The classic graph's downstream research roles — Evidence Steward, Bull/Bear,
Research Manager and Portfolio Manager — are code-owned and cannot be configured
by a preset. Evidence qualification and debate routing determine which execute.
Both typed modes (`company_research` and `holding_review`) route from Research
Manager directly to Portfolio Manager. Trader and the three risk analysts have
been retired from the execution graph; they are not an alternate runtime branch.

Built-in presets live in `tradingagents/presets/`. To create a local override
that survives package upgrades, place a file in `~/.tradingagents/presets/`
with the same `id`:

```yaml
id: news-first
label: 新闻优先
analysts:
  - news
  - market
```

The loader accepts only `id`, `label`, and `analysts`. Analyst IDs must be one
or more unique values chosen from `market`, `social`, `news`, and
`fundamentals`. Invalid local files are ignored and do not block the built-in
presets; `inspect_preset(path)` provides the same validation for tooling. Its
inspection checks syntax, allow-listed roles and the presence of fixed
convergence metadata. `tradingagents.analysts.MANDATORY_CONVERGENCE_NODE_IDS`
retains nine historical names, including the retired Trader/risk roles; it is
compatibility metadata, not evidence that those nodes exist in the current graph.
The executable topology is owned by `graph/setup.py`. YAML v1 deliberately
cannot declare nodes, edges, tools, variables or downstream input mappings.

For a deterministic, no-LLM command-line check before committing a local
preset, run:

```bash
tradingagents inspect-preset ~/.tradingagents/presets/news-first.yaml
```

On success it prints the requested analyst order and the code-owned
convergence metadata. Invalid YAML exits with status `2` and one
stable error line, so it is suitable for local scripts and CI checks.

Duplicate preset IDs in a single directory are rejected during catalog loading.
A valid file in `~/.tradingagents/presets/` may still override a built-in ID;
that is the documented upgrade-safe customization mechanism.

The code-owned `tradingagents.analysts.ANALYST_CONFIG` is the single metadata
registry for those selectable roles. It supplies the stable wire key, display
metadata, style, factory reference, graph-node identifiers, and API config
listing. The role factory itself stays in code and is allow-listed, so a YAML
file cannot import or execute an arbitrary implementation.

Preset order is part of the analysis request and resume fingerprint. Retrying
or resuming a run therefore uses the exact analyst order that created it.
