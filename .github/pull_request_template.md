## Documentation impact

Choose `No documentation impact`, or select every relevant documentation-impact surface:

- [ ] No documentation impact. The change does not alter architecture, public contracts, configuration or workflow, runtime behavior, deployment, or generated frontend assets.
- [ ] Architecture or component boundaries: updated `ARCHITECTURE.md`, scoped `AGENTS.md`, or the relevant architecture document.
- [ ] Public contracts or schemas: updated the relevant contract index and documentation for compatibility or consumer changes.
- [ ] Configuration or workflow: updated the affected README, operational reference, CI/workflow documentation, or configuration guidance.
- [ ] Runtime behavior: updated user-facing behavior, research, API, or operational documentation.
- [ ] Deployment or packaging: updated installation, deployment, release, or packaged-asset documentation.
- [ ] Generated frontend assets: ran `npm --prefix frontend run build` and committed the resulting `tradingagents/web/static/` changes.

Documentation surfaces changed (or explain why the selected impact does not need a doc change):

<!-- List paths, or write "None" when the first checkbox is selected. -->

## Validation

- [ ] I ran the focused validation for the changed surface.
- [ ] I confirmed that local Markdown links remain valid with `python scripts/check_agent_docs.py`.
