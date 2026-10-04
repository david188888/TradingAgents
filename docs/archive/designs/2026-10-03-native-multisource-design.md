# Native research multi-source admission

Status: Frozen Design

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

> 编写时状态：Approved scope — user selected unified multi-source capability routing
on 2026-10-03. Endpoint qualifications are established by probes and tests,
not by this design document.

## Objective and boundaries

Remove evidence_v1's hard dependence on Tushare identity, statements and calendar.
Company, catalyst and holding research share the same capability collector.
Primary candidates are existing a-stock-data-derived public HTTP adapters;
Tushare is a backup. Classic remains default; classic and old catalyst source
execution are not replaced. No push, PR, merge or default-profile migration.

Keep research-only, cutoff, units, exact security identity and reproducible
saved provenance. A failed capability does not erase other available
capabilities. Identity must still be qualified before facts can be admitted.
No missing result becomes a negative event finding or an estimated financial
value. Do not introduce model extraction or extra debate stages.

## Owning units

- `dataflows/native_sources.py`: native capability routing, source-specific
  HTTP retrieval through the supplied BudgetedSession and durable fetch cache.
  Produces existing FrozenEvidenceDraft and source context.
- Pure source qualifiers: normalize identity, statement fields and price inputs;
  reject wrong code, unit, date, malformed or incomplete payloads.
- `research/native_record.py`, `native_policy.py`, `verification_tools.py`:
  recognize a finite code-owned registry of qualified source families instead
  of assuming every financial/identity source is Tushare. Preserve source names.
- `execution/native_runner.py`: choose the native collector and bind source
  routing version to checkpoints. Continue to replay old saved V0 records
  without any new source calls. If an old interrupted run lacks V0, use its
  original collector/version; never mix source topologies in a frontier.

## Candidate chains and admission

| Capability | Ordered candidates | Required admission |
| --- | --- | --- |
| Identity | EastMoney push2 identity; Sina labelled company profile; Tushare stock_basic | exact code, name, exchange and valid listing date <= cutoff; no inference from code prefix alone |
| Official disclosures | CNINFO; existing exchange-official transport when exact scope/paging is supported | exact security, publication dates, complete pagination or explicit partial; titles are not body evidence |
| Financial statements | Sina direct; Tushare statements; other public statement candidates only after qualification | normalized CNY fields, consolidated scope, report period and actual disclosure date <= cutoff; reporting period is not disclosure date |
| Calendar | SZSE complete monthly calendar; Tushare trade_cal | complete natural-day grid in window, dates/open flags validated; calendar holes are not holidays |
| Adjusted prices | Tencent raw history + dated Sina factors; Tushare daily + factors | OHLC invariants, settled sessions, exact window, adjustment formula/anchor, input hashes and current-cutoff factor capture qualification |

Candidate lists are bounded and code-owned. `evidence_source_vendors` maps
`identity`, `financial`, `calendar`, `price` and `events` to ordered vendor lists;
an explicit list replaces that capability's native default (including an empty
list). `evidence_source_exclusions` is a list applied after selection. Unknown
capability/vendor values fail configuration validation. These keys are included
in semantic checkpoint identity. Legacy `data_vendors`/`tool_vendors` retain
their existing classic/catalyst meaning and do not override native routing.
An explicit native Tushare-only list is honored. Native
defaults select public sources before Tushare without reordering global
classic vendor defaults. Unsupported exchanges fail explicitly rather than
silently borrowing a different exchange's calendar or instrument data.

Sina statement transport must preserve all vendor metadata needed to establish
publication and units. When such metadata is absent, retain the missing reason
and try the next candidate. Do not invent a publication date from report end,
calendar deadlines, or a title-only match. A statement that cannot be admitted
may be saved as unavailable evidence; it must not enter facts or C1 checks.
Financial fallback occurs per table, using separate durable provider/table
keys. Keep each provider's admitted tables in a separate evidence bundle;
never combine Sina and Tushare into one source family. If Sina income qualifies
but its cashflow fails, retain income and try Tushare cashflow. C1 comparisons
still require current/base operands from the same exact saved family. Test
partial-primary plus qualified-backup admission and cross-family rejection.

Tencent/Sina preparation is a separate qualified input construction, not an
upgrade of Tencent's generic pit_unverified qfq endpoint. Raw and factors must
agree on instrument and price basis. Dated factors must cover every admitted
bar and never anchor to the future. Current capture is eligible only for the
current research date; older cutoffs require an archived vintage and otherwise
remain unavailable. Suspended/missing sessions remain explicit and cannot be
filled with synthetic prices. Risk statistics use the existing deterministic
script and never become intrinsic valuation or a substitute for a benchmark.

## Failure, budgets and replay

Each attempted provider has a distinct durable capability key; each underlying
HTTP attempt passes through BudgetedSession. Keep 24 capability/64 HTTP ceilings,
the active deadline, cancellation, and existing model/verification budgets.
Monthly calendar requests belong to one logical source capability and each
month consumes its own HTTP attempt. Do not use SDK/subprocess/network paths
with unobservable retries.

Persist only controlled failure codes and safe details, never full vendor
messages, tokens, request headers or config copies. Preserve attempted order,
selected source and gaps in capability detail. A known provider failure may
fall through to an independent configured provider. An unknown dispatched
attempt remains billed and is never redispatched under the same key.
Budget exhaustion and cancellation stop further attempts; checkpoint
conflicts/persistence failure must propagate rather than be swallowed as
provider errors. Saved response failures retain typed codes when replayed.

Skip further Tushare requests in the same run after a confirmed account-level
rate rejection; retain that fact explicitly. Cooling is run-local, rebuilt from
saved typed failures on resume. No credential rotation, retry storm or evidence
cache across cutoffs. Cooling must not block unrelated public sources.

## Compatibility and validation

Public research-record and source-content wire shapes remain v1. New family
names use the same saved content hashes and field representation; all
financial consumers and verification checks share the finite family registry.
No source is renamed as Tushare to satisfy existing validators.

Test exact primary selection without a Tushare token, fallback on typed provider
failure, independent table/capability degradation, deliberate wrong instrument,
future disclosure, unit ambiguity, factor gaps, truncated pagination, calendar
holes, budget/cancellation boundaries and cached replay with zero transport.
Test new source families through facts, specialist partitions, C1, report and
Reader projections in all three modes. Preserve old checkpoint identity and
legacy seed replay. Build static assets only if frontend source changes.

Run a bounded 002130 current-cutoff probe incrementally before a paid model run.
When identity, events and usable market/financial fields are established, run
one native research trial and verify Reader/API bytes and browser navigation.
If a provider cannot supply required qualifiers, report the actual coverage
gap rather than asserting research success. Keep engineering, source coverage
and predictive accuracy acceptance distinct. Synchronize architecture and
operational docs with the final implemented source policy.
