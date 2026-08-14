# Architecture Decisions

This directory records why a deliberate architecture choice was made. It is not a replacement for current code or the architecture map.

## Lifecycle

1. Open a small ADR when a choice affects module boundaries, public contracts, persistence, security, or compatibility.
2. Review it with the code owners and link the affected canonical sources.
3. Mark it `Accepted`, `Rejected`, `Superseded`, or `Deprecated`; do not silently rewrite an accepted decision.
4. Update the current architecture, contract index, and migration notes when the decision changes shipped behavior.

No historical ADRs are reconstructed in Phase 1. Existing reviews and plans remain classified in the [documentation index](../README.md).

## Template

Create a file named `NNNN-short-title.md` with this structure:

```markdown
# ADR NNNN: Short Title

- Status: Proposed | Accepted | Rejected | Superseded | Deprecated
- Date: YYYY-MM-DD
- Owners: names or team
- Canonical code: links to implementation and contract sources

## Context

What problem, constraint, or compatibility requirement led to this decision?

## Decision

What is being adopted, and which boundaries does it establish?

## Alternatives

What credible alternatives were considered, and why were they not selected?

## Consequences

What becomes easier, harder, or mandatory for future changes?

## Validation

Which tests, checks, or operational observations support the decision?
```

Keep an ADR concise. Put current field definitions in code and current dependency flow in [`ARCHITECTURE.md`](../../ARCHITECTURE.md).
