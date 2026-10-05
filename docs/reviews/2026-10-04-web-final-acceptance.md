# Web final implementation acceptance — 600803

Status: Local functional delivery verified; human reading and comparative research-quality acceptance remain open.

This is a dated verification record. Runtime truth belongs to
[Web evidence research](../operations/evidence-research.md), the canonical
schemas and [architecture](../../ARCHITECTURE.md).

## Approved scope and delivered behavior

The user selected option A: one native evidence-driven Web product, retaining
legacy history and saved recovery. CLI analysis is excluded from ongoing
maintenance; `tradingagents web` remains the local launch command. No history,
credentials or normal user-data directories were modified. All real validation
runs used a separate temporary run store.

- Single and batch creation default to `evidence_v1`. Explicit retired-profile
  creation and fresh legacy retry return typed rejection before preflight/enqueue.
  Saved legacy reads and identity-validated resume remain supported.
- Creation supports company research, 84-day catalyst research and holding review
  with declared holding facts. Batches remain company-only, 1–8 companies.
  Old profile, analyst/preset, debate-depth and horizon controls are removed.
  Provider/model selection includes validated actual custom model IDs in both
  single and batch panels; optional batch questions are visible before freezing.
- Workflow `evidence-production-v4` admits bounded qualified valuation sources,
  computes and validates a saved deterministic valuation context, and restricts
  dimension references before publication. One bounded semantic repair can fix
  invalid synthesis references without lowering the publication gate.
- Prior workflow collectors, prompts, dimension routing and original Markdown
  rendering remain available for saved recovery. Additive valuation is omitted
  from old records rather than changing their canonical hashes.
- The Reader presents one main judgement, principal risks, at most three grounds,
  valuation and quantitative context, next checks, then expandable evidence and
  verification. A single valuation anchor is explicitly labelled insufficient
  for cross-validation. Citations show saved content and metadata with inert
  background, Escape and return-focus behavior.

## Real trials and request ceilings

All cases use 600803.SS, cutoff 2026-10-04, configured DeepSeek and real saved
public/provider evidence. No live holdings were fabricated.

| Run | Source collection | SDK attempts | Outcome |
| --- | --- | ---: | --- |
| `run_20261004T143508985614Z_3d218955` | Fresh | 5 | Publication rejected for cross-dimension fact references; original failure preserved. |
| `run_20261004T144529085980Z_a62387d0` | Fresh, created through Web | 5 | Readable `partial / LOW_CONFIDENCE`; calendar throttling and invalid operating-stage output/repair remained visible. |
| `run_20261004T151705246468Z_32576e4c` | First run's frozen qualified seed, **0 new source attempts** | 6 | Published record, assessment `complete / LOW_CONFIDENCE`; all three dimensions conditional, all three challenges unresolved. |

Total: **16 actual SDK attempts**. The user expressly approved the third run
with a six-attempt ceiling. A guarded caller refused any seventh dispatch; the
source factory was set to reject fresh collection. Canonical evidence, claims,
metrics and snapshots were equal to the original seed. Only the new run identity
and deterministic valuation lineage were re-bound. Original runs were preserved.
The operating response needed one schema repair in the third run, within the
same six-attempt budget. No further paid requests were made.

The third run has 28 evidence items, 88 claims, nine hypotheses, three challenges
(one critical), six metrics and **zero independently executed verifications**.
Machine completeness means the dimensions/record were assembled; it does not
mean a fully qualified research conclusion. The Reader continues to label this
as limited research because its quality is LOW_CONFIDENCE.

## Valuation and source boundary

Qualified Tencent snapshot: price 19.20 CNY, PE-TTM 13.63, PB 2.53 and market
capitalization 594.28 亿元 (59.428 billion CNY), as of the proven
Shanghai settled session 2026-09-30. Tushare supplied 720 retrospective daily
multiple observations. Their vintage is the current capture, not historical
point-in-time archive proof. Sina financial fields retain disclosure/report dates
and source hashes; selected CNINFO excerpts retain bounded-body limitations.

The saved deterministic reference range is **12.82–20.50 CNY/share**, using a
single historical PE anchor and the admitted annual parent net-income base.
There is no admitted peer/forecast cross-check or second independent valuation
anchor. The range is conditional research context, not a proven intrinsic value.
The frozen trial neither re-tests current provider quotas nor fills missing
2026H1 report/operating bodies.

## Verification

- Full Python regression: **3,149 passed**, four live Wind tests skipped, one live
  DeepSeek class deselected, 74 subtests passed. Dotenv was disabled and pypdf used
  from an isolated temporary dependency path. Later focused valuation checks:
  14 passed; native admission/recovery checks: 60 passed.
- Frontend: **315 Vitest tests in 44 files**, typecheck and production build passed.
  Tracked generated SPA assets rebuilt from source. Lockfile installation passed.
- Playwright: **19 scenarios passed** against real HTTP/SSE/store boundaries with
  synthetic 600803 evidence and model substitutes; no paid calls. Includes three
  research scopes, custom-ID admission and single/batch switching, legacy Reader,
  saved-record reload, cancellation, focus, axe and reduced-motion checks.
- Real in-app browser: desktop 1440px, mobile 390px and a 720px CSS viewport
  showed no horizontal overflow. The 720px check is an equivalent narrow viewport,
  **not native browser 200% zoom proof**. Actual saved valuation references opened,
  Escape restored focus and removed background inertness.
- Before/after hashes of **473 files** in the isolated run store were equal after
  reading, expanding and opening/closing the latest record's sources. Reads
  dispatched no model/data work.
- Agent-doc link/navigation checks, scoped Ruff and `git diff --check` passed.

## Reviewable outputs and remaining work

The real Web workbench is shown at `http://127.0.0.1:8765/` for this session.
The self-contained exported report is served at
`http://127.0.0.1:8777/600803-report.html` and saved under
`output/web-final-600803/600803-report.html`, with its canonical JSON, original
partial report and actual desktop/mobile screenshots. Output files are ignored
local artifacts, not committed fixtures. The HTML preserves native expandable
saved details, removes JavaScript-only controls, and executes no scripts or API
requests. These temporary servers are session conveniences; normal usage is the
supported Web launcher.

Remaining acceptance is explicit:

1. Human reading/usability review of the delivered Web and HTML.
2. Multi-case comparative research quality, model consistency and predictive
   accuracy evaluation; the old paid evaluation protocol is not authorized here.
3. The 600803 report's open checks: half-year and operating-data bodies, cash-flow
   working-capital decomposition, debt maturities, peer valuation and forecasts.
   Closing these requires newly qualified evidence and appropriate bounded
   verification, rather than hiding gaps or converting provider failures to facts.
4. Live calendar/provider availability after rate limits reset; frozen replay
   cannot prove a fresh-source run will have complete coverage.

Local implementation and checks were complete at this acceptance snapshot. No
Git commit, push, PR, merge or remote deployment was performed or authorized at
that point.

## Publication authorization — 2026-10-05

The user subsequently authorized a subagent to publish a major GitHub update.
That authorization supersedes the snapshot's local-only publication restriction,
without authorizing additional paid evaluation or removal of user data. The
release scope and verification boundaries are recorded in the
[v3.0.0 release notes](2026-10-05-v3-release-notes.md). The GitHub PR and release
provide publication evidence; publishing does not close the remaining human
reading or research-quality acceptance above.
