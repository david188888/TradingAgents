# Workbench analyst presets

- **Status: Current**

The workbench loads YAML presets for the four existing analyst roles. A preset
can enable a subset and choose their execution order; it cannot add tools,
agents, prompts, retries, or graph edges.

The downstream decision roles — Evidence Steward, Bull/Bear, Research Manager,
Trader, the three risk analysts, and Portfolio Manager — are fixed graph nodes
that a preset cannot configure. Whether each node actually executes depends on
the research `mode` and conditional routing, not on preset selection. In the
two supported typed modes (`company_research` and `holding_review`), the graph
routes from Research Manager directly to Portfolio Manager; Trader and the
three risk analysts are skipped entirely. The legacy upstream-compatible graph
branch that runs Trader and the risk debate is retained for compatibility with
older runs, but it is not selected by current typed request modes.

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
dry-run invariant confirms that any accepted non-empty analyst sequence
terminates in the code-owned convergence path (the nine downstream nodes above
are registered in `tradingagents.analysts.MANDATORY_CONVERGENCE_NODE_IDS`);
YAML v1 deliberately cannot declare nodes, edges, tools, variables, or
downstream input mappings. Being part of that fixed path means the nodes exist
and are not preset-configurable; it does not mean each one runs on every
analysis.

For a deterministic, no-LLM command-line check before committing a local
preset, run:

```bash
tradingagents inspect-preset ~/.tradingagents/presets/news-first.yaml
```

On success it prints the requested analyst order and the code-owned
mandatory convergence roles. Invalid YAML exits with status `2` and one
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
