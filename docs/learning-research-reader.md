# TradingAgents 学习型研究与 Reader

**状态：** Legacy composite reference; pending staged decomposition
**最近核验：** 2026-08-13
**适用范围：** 学习型公司研究、持仓复盘、Research Case、Thesis Diff、Reader、Companion 与 Audit Center

> **迁移提示：** 本文约 1,800 行正文在 Phase 1 原样保留，供兼容、历史核对和迁移使用。它不再是唯一或权威的架构、契约、状态来源；当前入口见 [docs/README.md](README.md)，当前架构见 [ARCHITECTURE.md](../ARCHITECTURE.md)，机器定义的契约见 [docs/contracts/README.md](contracts/README.md) 与代码。计划、设计和验收记录仍按其文档分类处理，不应覆盖当前实现事实。

本文正文保留既有产品边界、系统流程、稳定契约和实现记录。内容移动、拆分或删除属于后续阶段；在此之前，若本文与代码不一致，以代码和测试为准，并在同一修复中更新对应的权威文档。

## 1. 产品定位

TradingAgents 的学习型路径用于理解公司、股票、行业、风险和研究论点，也可复盘现有或模拟持仓。它不是券商、订单系统、组合会计系统或个性化投资顾问。

系统提供两个显式模式：

- `company_research`：默认模式，生成独立的公司研究结论。
- `holding_review`：在相同研究主体上增加成本、集中度、盈亏敏感性和原始持仓理由复核。

每次运行选择一个研究周期：

- `short`
- `medium`（默认）
- `long`

两种模式都不得产生：

- Buy/Hold/Sell 交易评级；
- 推荐或目标仓位；
- 买卖数量、分批动作或订单参数；
- 券商连接、交易执行或实盘确认；
- 对缺失账户事实、市场价格、币种或用户理由的推测。

允许的顶层研究倾向只有：

- `favorable`
- `neutral`
- `cautious`
- `insufficient_evidence`

持仓复盘中的金额和集中度仅是描述性结果，并始终带有 `learning_only_no_transaction_instruction` 边界。

## 2. 当前系统流程

```text
Controls
  → RunCreateRequest
  → compatibility normalization
  → RunSnapshot / fingerprint / run.started
  → deterministic horizon and data prefetch
  → analysts + Evidence Steward + research debate
  → evidence-bound claim drafts
  → ResearchCaseV2 assembler and eligibility policy
  → durable research-case-v2 artifact
  → run.completed
  → best-effort thesis-diff-v1 artifact
  → GET /api/runs/{run_id}/reader
  → Reader surface
  → on-demand Companion / Audit Center
```

### 2.1 数据层

周期策略、数据窗口、分页预算、复权要求和 required/optional 能力由
`horizon-policy-v2` 确定，不由 LLM 临时决定。v2 增加了逐来源 typed
结果、A 股官方披露 any-of 规则，以及验证身份/快照的来源闭包；旧 checkpoint
不会被当成相同运行语义继续使用。

每个数据能力区分：

- 请求范围与实际观测范围；
- `complete / partial / unknown / unavailable`；
- 页数、是否耗尽和预算截断；
- as-of、降级原因与来源身份。

核心研究能力还持久化 `CapabilityResultV1` 与逐来源
`ProviderAttemptV1`。可用性不再从错误文本推断，而是明确区分：

- `available / partial`
- `not_covered`：已实际询问全部必需来源，权威返回无覆盖；
- `not_supported`：当前版本没有实现该生产者；
- `provider_unavailable`：供应商失败、冷却或尚未实际观测；
- `invalid`：身份、截止时间或载荷契约无效。

每轮研究在任何时敏抓取前冻结 `analysis_cutoff_at`。A 股使用
`Asia/Shanghai` 分析日边界；全球标的必须先解析可验证的交易所时区。
无法解析时，价格、新闻和公告抓取不会启动，并持久化 typed invalid
结果供重放和审计。

当前确定性预取链包括：验证身份、市场快照、复权价格、公司事件、官方
披露，以及按周期约束的季度/年度三表。分析师工具优先重用这些冻结数据包，
避免同一轮研究二次抓取产生漂移。

中长期技术结论要求明确的复权序列。复权数据不可用时，不得用 raw price 推断趋势。历史分析不得混入分析日之后的新闻、公告或当前快照。

### 2.2 研究层

分析师只消费已提交的数据包。Research Manager 输出使用短稳定 claim key 的结构化草稿；assembler 将其解析为当前运行中的 evidence/coverage 引用，并确定性计算 source dates、资格和数据质量。

事实 claim 还必须通过代码拥有的 lens-capability 校验：market 仅接受身份、市场快照和复权价格，fundamentals 仅接受季度/年度基本面，news 仅接受公司事件与官方披露，其余 A 股补充能力才可归入 sentiment。不可用的 typed capability 不会出现在 Research Manager 的候选 key 中；错配 fact 会被 assembler 删除，eligibility 会独立复验一次，模型文本不能升级结论资格。

旧 Markdown 报告保留用于兼容和审计，但不得反向解析为新版事实。

### 2.3 公开产物层

Reader 只消费已经 durable commit 的公开产物。目前受控的派生契约是：

- `research-case-v2`
- `thesis-diff-v1`

`research-case-v2` 通过 graph commit 后的 promotion 通道发布，绑定当前
run、来源 graph task、checkpoint event 和 committed sequence。跨 run、
未知契约或没有提交身份的输入必须失败；重放必须幂等。

`thesis-diff-v1` 走独立的 post-completion best-effort 通道：它在
`run.completed` 之后写入 content-addressed artifact，沿用 Research Case 的
committed sequence，并记录来源 Research Case artifact、来源 completed event
和 `publication_phase=post_completion`。artifact 事件以 `run.completed` 为父
事件，并在当前 run 锁内按来源 artifact + event 幂等发布。它不伪装成 graph
task/checkpoint 产物，也不能直接套用 Research Case 的 graph commit 语义。

### 2.4 阅读与审计层

默认 Reader 按以下顺序服务日常阅读：

1. 模式、周期、研究倾向、资格和数据质量；
2. 已验证事实、分析推论、尚待验证；
3. 三情景、催化剂、失效条件和复核计划；
4. 跨 Run 论点变化；
5. 分析师卡片和数据限制；
6. Companion 与 Audit Center 入口。

Prompt、locator、内容哈希、完整 CSV、供应商 raw payload 和内部调试快照不得进入默认 Reader 响应或初始 DOM。

## 3. 稳定契约与不变量

### 3.1 输入契约

新请求默认：

```text
mode = company_research
horizon = medium
```

`company_research` 不得携带 `holding`。

`holding_review` 的最小输入为：

```text
ticker: normalized target ticker
quantity: finite number > 0
average_cost: finite number > 0
```

以下事实可选，缺失时保持未知：

```text
cash
total_account_value
currency
facts_as_of
original_thesis
```

`facts_as_of` 缺失时归一化为分析日期；显式提供时必须与分析日期一致。系统不从现金推导总资产，不从证券身份推导用户金额币种，也不从平均成本推导当前市场价格。

Mode、horizon 或任一归一化持仓事实变化都会改变 fingerprint，不能复用旧 checkpoint。

Legacy `portfolio` 只保留在兼容边界。无法唯一、安全地映射目标持仓时必须拒绝恢复，不能静默转为公司研究。

兼容归一化顺序是冻结契约：

| 输入 | 结果 |
|---|---|
| `holding` 与 legacy `portfolio` 同时存在 | 拒绝 |
| 显式 `company_research` 携带任一持仓输入 | 拒绝 |
| 显式 `holding_review` + `holding` | 使用新契约 |
| 显式 `holding_review` + legacy `portfolio` | 执行 legacy 映射 |
| mode 缺失 + `holding` | 推断 `holding_review` |
| mode 缺失 + legacy `portfolio` | 推断 `holding_review` 并映射 |
| mode、holding、portfolio 均缺失 | 推断 `company_research` |

Legacy 映射必须按规范化 ticker 得到唯一目标持仓，并验证 quantity 与
average cost；不得从 mark price、cash 或交易限制推导新版持仓事实。无法
归一化的旧快照返回 `legacy_resume_normalization_failed`。

公开 422 code/path 也是冻结契约：

| code | path |
|---|---|
| `holding_required` | `holding` |
| `holding_not_allowed` | `holding` |
| `legacy_portfolio_not_allowed` | `portfolio` |
| `holding_legacy_conflict` | `portfolio` |
| `holding_ticker_mismatch` | `holding.ticker` |
| `holding_quantity_invalid` | `holding.quantity` |
| `holding_average_cost_invalid` | `holding.average_cost` |
| `holding_cash_invalid` | `holding.cash` |
| `holding_nav_invalid` | `holding.total_account_value` |
| `holding_currency_invalid` | `holding.currency` |
| `holding_as_of_invalid` | `holding.facts_as_of` |
| `holding_as_of_mismatch` | `holding.facts_as_of` |
| `legacy_target_position_missing` | `portfolio.positions` |
| `legacy_target_position_ambiguous` | `portfolio.positions` |
| `legacy_target_position_invalid` | `portfolio.positions` |

`run.started.holding_summary` 在公司研究中为 null。持仓复盘只公开 ticker、
quantity、average cost、currency、facts_as_of、source 和三个布尔存在标记；
不得重复 cash、NAV 或 original thesis 正文。

前端切回公司研究时必须清除隐藏持仓字段的请求语义。未填写的可选字段
必须省略，不能发送空字符串。

集中度、未实现盈亏和情景敏感性仅在以下事实齐备时计算：analysis-date
对齐的可信市场价格、已验证且一致的金额/报价币种，以及对应计算所需的
用户事实。否则输出结构化 unavailable，稳定 reason code 包括：

- `total_account_value_not_provided`
- `verified_market_price_unavailable`
- `currency_unverified`
- `currency_mismatch`

缺少 `original_thesis` 不影响集中度、未实现盈亏或情景敏感性计算；它只让
原始论点复核输出 `original_thesis_not_provided`。

### 3.2 ResearchCaseV2

`ResearchCaseV2` 是学习型 Reader 的唯一结构化研究主体。每个公开 claim 必须是以下一种：

- `fact`：有当前 run 的 evidence 与 coverage 引用，并可验证 source date；
- `inference`：引用支持它的事实或证据，明确置信度；
- `unknown`：明确缺失项、原因和下一验证动作。

未知 schema major、重复 claim key、跨 run evidence、不可用 evidence、无 coverage 的事实或不完整 unknown 必须被确定性拒绝。

资格和数据质量由代码拥有的政策计算，不由模型语气决定：

- `decision_eligibility`: `full | limited | none`
- `evidence_verdict`: `PASS | LOW_CONFIDENCE | FAIL_STOP | GATE_ERROR`
- `data_quality`: `healthy | limited | conflicted | blocked`

必需能力若为 partial/stale，资格至多为 `limited`；若为
`not_covered / not_supported / provider_unavailable / invalid`，仍可展示已经
验证的局部事实，但顶层研究倾向强制为 `insufficient_evidence`，并由代码
补充未知项与下一验证动作。可选能力失败不会强制改变顶层倾向。

当前全球中长期研究的 `sec.company_filings` 尚未实现，因此会明确产生
`not_supported: official_filings_provider_not_implemented`；运行可完成，但
资格为 limited，倾向为 insufficient_evidence。不得用新闻搜索或第三方摘要
伪装为 SEC 官方披露。

Registry 对重试结果按 committed sequence、event sequence 和 artifact ID
确定性选择。选中的 artifact 哈希损坏、跨 run/跨标的链接或已选择的截止日后
证据不会降级成普通缺失，而会发布不含实质性 claims 的 `FAIL_STOP` 安全壳。

### 3.3 ThesisDiffV1

ThesisDiff 在稳定 `run.completed` 之后 best-effort 生成，失败不得改变 Run 或 Research Case 状态。

基线必须满足：

- completed；
- 同一规范化 ticker；
- 同一 horizon；
- 可解析 `research-case-v2`；
- 候选 `(completed_at, run_id)` 元组严格小于当前运行的对应元组。

因此相同 `completed_at` 可以用 `run_id` 确定性排序；Mode 不影响基线选择。

五种变化状态为：

- `new`：本轮新出现；
- `maintained`：核心内容和状态保持；
- `invalidated`：当前明确失效且存在反证引用；
- `unresolved`：当前仍是未知；
- `not_reassessed`：旧论点本轮没有复核。

旧 claim 从本轮消失绝不自动等于 `invalidated`。文本比较执行 trim、NFC 和空白折叠；evidence 按 ref 集合比较；confidence 变化阈值为 0.01。

### 3.4 Reader 与降级

`GET /api/runs/{run_id}/reader` 返回封闭判别联合：

- `LearningReaderV2`
- `LegacyReaderV1`
- `ReaderUnavailableV1`

规则：

- typed case 投影失败返回 unavailable，不降格成 legacy；
- thesis diff 缺失或损坏不影响 Reader 主体；
- 没有历史基线但 diff 正常时，当前 claim 按确定性规则为 new/unresolved；
- legacy run 明确标记历史格式，不伪造新版字段；
- Reader 投影是纯读取，不调用 LLM、网络或写入存储。

### 3.5 Companion 与 Audit 边界

Companion 已提供只读端点
`GET /api/runs/{run_id}/reader/companion?kind=...&id=...`。契约只允许
`role / claim / evidence / risk` 四类公开 selection，并校验选择属于当前 run。
未知、跨 run、legacy 或不可公开 ID 统一返回 typed 404；端点没有 raw fallback。
DTO 只返回 selection、摘要、实际覆盖、结论影响和下一验证。

Audit Center 已作为独立终态工作区完成。它仅在用户主动进入后加载角色、
能力、工具和 artifact 安全摘要；单项详情需要第二次显式选择，大型内容只返回
元数据和下载入口。运行期间的 Inspector 仍是独立的实时审计栏。

默认 Reader 已移除 `audit_entry.audit_refs` 以及 ThesisDiff 的当前/上一 Research
Case artifact ID，只保留审计计数和安全公开引用。递归契约测试同时检查序列化
Reader 与初始 DOM，禁止 content-addressed ID、locator、hash 和 raw content，
而不只检查顶层字段名。

## 4. 当前实现状态

下表列出的能力均已进入 `main`；本轮没有开放的 Reader 实施路线。

| 能力 | 状态 | 依据 |
|---|---|---|
| 双模式、三周期和最小持仓输入 | Merged | `c4eff4d`, `d6fd21e` |
| 周期数据、新闻/公告分页、A 股补充能力 | Merged | Phase 0 commits and tests |
| 确定性复权价格降级 | Merged | `3ce5fb9` |
| Evidence/Coverage registry | Merged | `c12a432` |
| Evidence-bound claim drafts | Merged | `5194590` |
| ResearchCaseV2 assembler 与资格接线 | Merged | `25a4365` |
| 真实 LLM 结构化输出与终态修复 | Merged | `d09dae5`, `28ac8d5`, `24af92b` |
| Reader Core API：typed/legacy/unavailable | Merged | `154d5ef` |
| Reader 第一屏 | Merged | `1bfa560` |
| ThesisDiffV1、发布幂等、provenance 与可复现测试 | Merged | `2f818bf`，经 PR #5 合入 `main`（`1f7b258`） |
| P2-2 学习报告与论点变化 | Merged | PR #5 / `1f7b258` |
| P2-3a Companion DTO/API 与 Reader 隐私收口 | Merged | PR #5 / `1f7b258` |
| P2-3b 自适应伴读栏 | Merged | PR #5 / `1f7b258` |
| P2-4 独立 Audit Center | Merged | PR #5 / `1f7b258` |
| P2-5 视觉、响应式、可访问性与 golden QA | Merged | PR #5 / `1f7b258` |
| 合入 CI 合同 | Merged | `88e3681`，经 PR #5 合入 `main` |
| 分析截止时点、typed capability 与来源尝试契约 | Merged | `80746ad`–`12a82cc` |
| 数据路由、身份、新闻时区与 OHLCV 时点修复 | Merged | `8798962`–`fcef49d` |
| fundamentals / official durable bundles 与六格策略闭包 | Merged | `1749096`–`5e42aa3` |
| Registry、claim capability、eligibility 与 required-prefetch 闭包 | Merged | `9cbf5de`–`a3e1dec` |

已验证的 typed run：`run_20260810T152235678110Z_aa9f06e0`。它包含 6 个 claims、4 个 analyst cards、partial availability 和 `eligibility=none`，可用于本地 Reader 验收；不得将其私有原始内容提交为 fixture。

### 4.1 当前验证基线与能力边界

2026-08-13 的数据完整性门禁为 122 passed；完整后端套件为 1713 passed、
28 failed。未通过项仍包含旧契约/图拓扑断言、live 网络与 Wind 环境依赖，
不能把当前分支描述为全仓全绿。前端 typecheck 和 Reader/Audit 定向测试通过；
完整 Vitest 仍有 2 个与当前未提交 UI 改动对应的旧断言失败。

六格策略中，A 股 short/medium/long 与 global short 在 required evidence 完整时
可以达到 full。Global medium/long 因 `sec.company_filings` 尚未实现，必须保持
limited 并强制 `insufficient_evidence`，不得由第三方新闻或模型判断绕过。

### 4.2 下一阶段现役路线

当前只维护下面一条演进顺序；跨模型适配继续按用户要求延期：

1. 实现 SEC submissions/filings、accepted timestamp、分页 coverage 和 cutoff，
   并把一次运行聚合为统一 `PointInTimeEvidenceSnapshot`；
2. 将 A 股 `verified_identity` 收紧到公司名称、证券类型和上市状态可验证；
3. 让生产 E2E fixture 发布 `research-case-v2` 与 typed capability audit；
4. 在上述事实层稳定后增加代码化 `ConflictSummary`、教育型
   `ResearchLensResult` 和 `LearningTrace`。

外部仓库审计仅用于确定实现优先级：PIT snapshot 借鉴 ai-hedge-fund，冲突与
质量状态借鉴 daily_stock_analysis，教育型 lens 借鉴 serenity-skill/finskills，
A 股 failure-domain 防护借鉴 a-stock-data，证据缺口规划借鉴 Dexter。自动交易、
仓位优化、收益排行、P&L 奖励、跟单和名人 persona 不进入现役产品路线。

### 4.3 SEC、PIT snapshot 与严格身份设计（Approved Design，尚未实现）

本节是下一实施切片的已批准设计。实现完成前，第 3.2 节所述 global
medium/long `not_supported` 行为仍是现役事实；本节不得被解释为已经上线。

#### 4.3.1 范围与非目标

- 首阶段完整支持美国 SEC reporting companies；其他 Global 市场继续明确
  `not_supported`，不以第三方新闻或模型推断冒充监管披露；
- 完整索引窗口内的 10-K、10-Q、8-K 及其 amendments；冻结并解析 10-K/10-Q
  primary document，8-K 首阶段只保留完整元数据与 SEC 原文链接；
- SEC 访问必须显式配置 `TRADINGAGENTS_SEC_USER_AGENT`，未配置时不发请求；
- `PointInTimeEvidenceSnapshotV1` 先作为内部 durable contract，不改变 Reader
  公共 schema；
- 跨模型适配、其他监管机构、8-K 全文批量解析和 Reader 新布局不在本切片。

SEC 官方 Submissions API 无需 API key，单个 CIK 的 recent 结构至少包含最近
一年或最近 1,000 条 filing，并通过附加 JSON 文件声明更早历史；实现必须按
窗口读取相关历史文件，而不是只看 recent。访问必须遵守 SEC 公布的自动访问
策略；客户端默认限制为每秒 5 次请求，低于当前每秒 10 次的公开上限。

权威参考：

- `https://www.sec.gov/search-filings/edgar-application-programming-interfaces`
- `https://www.sec.gov/about/webmaster-frequently-asked-questions`

#### 4.3.2 内部契约

```text
VerifiedInstrumentIdentityV1
  ticker, market, company_name, security_type,
  listing_status, exchange, regulatory_authority,
  cik, availability, verification_level,
  field_facts[value, source_id, observed_at, effective_at],
  provider_attempts, content_hash

VerifiedIdentityCapabilityResultV1
  base CapabilityResultV1,
  identity_artifact_ref, identity_content_hash,
  verification_level

SecFilingIndexV1
  cik, company_name, requested_window,
  fetched_history_files, pagination_exhausted,
  source_artifacts[role, artifact_id, content_hash],
  coverage[index_search_complete, observed_index_count,
           target_filing_count, rejected_target_count,
           required_document_count,
           completed_document_count],
  filings[form, accession, filing_date,
          accepted_at, report_date, primary_document, sec_urls,
          source_artifact_ref, document_ref]

SecFilingDocumentV1
  accession, form, accepted_at,
  raw_artifact_ref, normalized_text_artifact_ref,
  parser_status, content_hash

PointInTimeEvidenceSnapshotV1
  schema_version, run/ticker/cutoff/identity references,
  source_committed_sequence, resolved_plan_id/hash,
  selections[capability, capability_result_id, artifact_id,
             evidence_refs, coverage_refs],
  artifact_closure, missing/degraded capabilities, snapshot_hash

SnapshotPublicationV1
  snapshot_artifact_id, source_committed_sequence,
  registry_through_sequence, resolved_plan_hash
```

大正文不复制进 snapshot。原始 SEC HTML 先作为 durable artifact 保存，再生成
规范化文本；解析失败不能破坏已经冻结的原始证据。单文档下载和解析必须有
固定预算，超限不得截断后伪装完整。

Identity 的 `availability` 表达供应商是否成功观测，`verification_level` 表达
已观测字段的证明强度；两者不得互相推导。SEC current submissions、每个被读取
的 history JSON 和每份 primary document 的 raw bytes 都必须先冻结为 artifact，
index 只能引用这些 artifact，不能只留下远端 URL。

`VerifiedIdentityCapabilityResultV1` 是 identity capability 的唯一 typed result。
它在现有 `CapabilityResultV1` 语义上增加 identity artifact/hash 与
verification level；这些字段参与 capability result semantic ID，并进入 Snapshot
artifact closure。Eligibility 明确要求 required `verified_identity` 同时满足
generic available/current/complete 和 `verification_level=full` 才能得到 full；
generic complete 但 verification 为 partial 时，eligibility 至多 limited。

#### 4.3.3 策略解析与数据流

为避免 identity、cutoff 和历史 listing status 互相循环，pre-graph prerequisite
顺序固定为：

```text
InstrumentIdentityPreflightV1
  ticker, candidate exchange/timezone/regulatory scope
  -> freeze AnalysisCutoffV1
  -> VerifiedInstrumentIdentityV1(as-of cutoff)
  -> regulatory scope resolution
       |-- us_sec_candidate
       |-- global_non_sec
       `-- unresolved
  -> freeze ResolvedDataWindowPlanV3 + semantic hash
  -> checkpoint authorization
  -> graph prefetch consumes the frozen plan
```

Preflight 只提供冻结 cutoff 所需的候选交易所、时区和监管范围，不得声称公司
名称、证券类型或上市状态已经 verified。cutoff 后执行字段级身份验证，再冻结
resolved plan。preflight、cutoff、verified identity、resolved plan ID/hash 和
SEC User-Agent configured boolean 必须进入 initial-context fingerprint；所有
prefetch 只能消费该冻结 plan，不得在节点内按 `market` 重新构建策略。scope
为 unresolved 时不得发 SEC 请求。

- `us_sec_candidate` 的确定性谓词是：equity/company 标的具有无冲突的已观察
  美国主交易所或美国司法辖区事实；它只表示应该执行 SEC provider policy，
  不宣称 SEC 已覆盖该公司。缺少 User-Agent 或 SEC outage 不改变这个 scope；
- `us_sec_candidate` 的 medium/long required source 是
  `sec.company_filings`；
- SEC ticker map 健康且无 CIK 时 official 结果为 not_covered；User-Agent 缺失
  或 SEC provider outage 时 scope 仍为 `us_sec_candidate`，official 结果为
  provider_unavailable；
- `global_non_sec` 保留 required 能力，但生产者明确返回
  `regulatory_provider_not_implemented`，其谓词是已观察且无冲突的非美国主交易所
  或监管辖区；
- `unresolved` 只用于交易所/司法辖区缺失或已观察事实冲突，为 `invalid`，不能
  猜测监管机构；
- policy version、方法资产和 runtime fingerprint 同步升级；
- 测试矩阵从 A 股/global 扩展为 A 股、US SEC、非 SEC Global 三种 scope。

SEC 流程固定为：以官方 ticker map 得到候选 CIK，使用 submissions 的名称、
ticker/exchange 与 CIK 验证身份，获取 current submissions 与窗口相交的历史
JSON，只保留 `accepted_at <= cutoff` 的目标 forms，下载 10-K/10-Q primary
documents，生成 typed official result，最后进入 PIT snapshot。目标 form 集精确
为 `10-K`、`10-K/A`、`10-Q`、`10-Q/A`、`8-K`、`8-K/A`。accession 是唯一键；
recent/history 重复且内容一致时去重，关键字段冲突时为 invalid。`accepted_at`
必须按 SEC timestamp 规则转换为 timezone-aware instant；缺失或非法时不得退回
filing date。流程顺序固定为先解析 accepted time、cutoff filter 和 accession
dedupe，再下载需要的文档。duplicate critical fields 固定为 `form`、
`filing_date`、`accepted_at`、`report_date`、`primary_document` 和 CIK；同一
accession 任一关键字段冲突即 invalid。submissions 的无 offset
`acceptanceDateTime` 按 `America/New_York` 在该日期的 DST 规则解释，再统一转
UTC。cutoff 后接受的 amendment 或 restatement 不得改写历史分析。

history manifest 的 `filingFrom/filingTo` 缺失或非法时不得跳过对应文件：在预算
内保守抓取并从实际内容判断；预算不足以读取所有无法判定范围的文件时搜索不
完整，结果为 partial。目标 filing 的 accepted timestamp 缺失或非法时不得用
filing date 替代，该项进入 `rejected_target_count` 并使结果至多 partial。

A 股身份分层规则：

- CNINFO/交易所确认 ticker、规范化公司名称、证券类型和上市状态或生效日期，
  才能得到 full；
- 官方源不可用时，Tushare 与 EastMoney/AKShare 两个独立来源一致只能得到
  partial，eligibility 至多 limited；
- 仅交易所后缀正确不能满足 `verified_identity`；
- ticker、名称、证券类型或上市状态发生来源冲突时为 `invalid`，阻止实质性
  claims；
- 历史 listing status 必须按 cutoff 判断；缺少生效日期时至多 partial。

每个 identity 字段必须分别保存规范化值、source ID、observed time 和 applicable
effective time。partial 要求 Tushare 与 EastMoney 或 AKShare 中至少一个独立来源
对 ticker、名称、证券类型和交易所逐字段一致；不能仅比较最终合并后的 profile。
provider failure 只进入 attempt/availability，不产生退市、证券类型或公司名称
事实；只有两个或以上已经成功观测并规范化的字段事实冲突才产生 invalid。
suffix-only 为 unavailable，不是 partial/full。Global 历史身份若只能取得当前
ticker map，必须由 cutoff 前 filing header/metadata 进一步绑定，否则至多 partial。

AnalysisCutoff 不得指向运行时尚未发生的未来时刻。若 analysis date 是市场本地
当前日期，cutoff 冻结为 `min(market_eod, preflight_captured_at)`；若是过去日期，
使用该市场日 EOD；未来 analysis date 为 invalid。这样同日盘中运行不会把当天
稍后才可能出现的 filing 计入“完整可观测窗口”。

#### 4.3.4 失败语义与访问纪律

| 情况 | Typed 结果 |
|---|---|
| SEC User-Agent 未配置 | `provider_unavailable / sec_user_agent_not_configured` |
| ticker map/submissions 请求失败 | `provider_unavailable` |
| 健康 ticker map 中没有美国标的 | `not_covered / sec_cik_not_found` |
| 非 SEC Global 市场 | `not_supported / regulatory_provider_not_implemented` |
| CIK/ticker/name/accession 身份冲突 | `invalid`，进入 FAIL_STOP |
| 完整遍历窗口且没有目标 forms | `not_covered / no_target_filings_in_window` |
| 历史分页未耗尽或必要正文缺失 | `partial` |
| 正文解析失败但原始 HTML 已冻结 | `partial / normalized_text_unavailable` |
| 索引、必要正文与 cutoff 完整 | `available` |

SEC 使用必填字段的 `SecDisclosureCoverageV1` validator，并向
`SourceCoverageV1` 投影 `observed_unit_count` 与 `search_complete`。唯一映射为：

- incomplete search + zero usable target → coverage unknown、availability partial；
- incomplete search + 至少一个 usable target → coverage partial、availability partial；
- exhaustive search + zero target 且 rejected_target_count=0 → unavailable coverage、
  availability not_covered；
- 任一 target 因 accepted timestamp 或必要文档不可验证而 rejected/incomplete →
  coverage partial、availability partial；
- exhaustive search + 全部必要 evidence 完成 → coverage complete、availability
  available。

generic coverage 的零 usable item 只有两个合法例外：

- `observed_unit_count > 0 && search_complete=false` →
  `item_count=0`、completeness=unknown、availability=partial；
- `search_complete=true && rejected_target_count>0` →
  `item_count=0`、completeness=partial、availability=partial。

`search_complete=true && rejected_target_count=0 && item_count=0` 必须是
completeness=unavailable、availability=not_covered。前两个例外表示已经观察到
索引或目标，但尚无可用 filing evidence，不代表公司没有 filing。只存在
8-K/8-K-A 且索引元数据完整时可
available；任何保留的 10-K/10-Q 及其 amendments 都必须完成 raw 与 normalized
document 才可 available。`SecFilingIndexV1.coverage` 是搜索和文档完成度的权威
细分，generic coverage 只是与现有 eligibility 的唯一兼容投影。

SEC transport 私有读取 `TRADINGAGENTS_SEC_USER_AGENT`；其他配置、事件、异常、
artifact、cache key 和 fingerprint 只能看到 `configured: bool`。通用 redactor
同时把 `user_agent`/`sec_user_agent` 视为敏感配置名。限速为每进程、每 SEC
host 一个 5 requests/second token bucket，最大并发 2；429 尊重 `Retry-After`
并进入 host cooldown，403、5xx 和网络超时进入既有 provider health/cooldown，
同一资源在单 run 内不紧密重试。

连接 timeout 为 5 秒、读取 timeout 为 30 秒、规范化 parser timeout 为 10 秒，
单份 primary document 最大 20 MiB。允许的正文 content type 为 `text/html`、
`application/xhtml+xml` 和 `text/plain`；其他类型、超限和 parser timeout 分别
记录 `invalid_content_type`、`oversize`、`parser_timeout`。raw hash 基于完整原始
bytes；规范化文本执行确定性字符集解析、移除 script/style、Unicode NFC、换行
与段落空白归一化后单独计算 hash。任何超限或超时都不得保存截断正文。
submissions JSON 可以短期缓存；accession 文档按 raw content hash 长期复用。

#### 4.3.5 Snapshot 发布与重放

```text
required prefetch graph tasks
  -> durable bundle artifacts
  -> Registry integrity validation and canonical selection
  -> point-in-time-evidence-snapshot-v1
  -> ResearchCase assembler consumes frozen selections
  -> research-case-v2
```

snapshot 在 durable prefetch artifacts 已提交后、Research Case 组装前生成。它
固定 capability result、artifact、evidence/coverage refs、来源身份、时间语义、
availability/freshness 和 content hash；canonical 排序后计算 semantic hash。
发布使用两个不可混淆的序列边界：`source_committed_sequence=C` 是 Research
Case 所在 accepted graph commit marker 的业务提交边界；marker 类型只允许
committed `graph.step_applied` 或 `graph.checkpoint_committed`。
`registry_through_sequence=E` 是 Registry
`read_events(through=E)` 的包含式物理读取边界。实现必须先完成由 C 及所有更早
accepted marker 所授权的预期 Registry-visible publication，包括 evidence bundle、
SEC closure、`report.updated` 及其 backing artifact，再设置显式阶段屏障并一次性
冻结 E，最后构建 snapshot；
不得依赖 Research Case 所在 commit 恰好最后执行。必须满足 `E >= C`，且
snapshot 与 Research Case 自身事件 sequence 均大于 E。

Registry 读取到 E 后，只接受同时满足以下条件的 v3 evidence：事件
`sequence <= E`；child 与 parent 的 status 都是 committed；整数
`payload.committed_sequence <= C`；parent 属于同一 run；parent sequence 等于该
committed sequence；artifact event 晚于 parent。lineage 分成两个且仅两个 profile：

- `graph-commit`：parent 是 `graph.step_applied` 或
  `graph.checkpoint_committed`，`graph_task_id` 必须位于 parent 的 applied task IDs；
- `pregraph-plan`：parent 是 committed `research.plan_resolved`，只允许 verified
  identity/plan artifacts，必须匹配 parent 的 identity ref、plan hash 与 run，且不得
  伪造 graph task identity。

缺失或非整数 committed sequence 是 integrity failure，不能默认为 0。既有 run、
ticker、hash、cutoff 和 capability result identity 校验继续执行。

`registry_through_sequence` 是发布和重放元数据，不参与 snapshot semantic hash；
同一 C 即使恢复后的物理 event 位置不同，只要冻结选择相同，snapshot hash 必须
相同。snapshot artifact/event 先于 Research Case artifact 发布，但两者携带相同
的 source committed sequence；assembler 只消费冻结 snapshot，不得重新
canonical-select。每个 SEC index/document 引用也必须递归校验 run、ticker、hash
和 `accepted_at <= cutoff`。

v3 的 `report.updated` 与 backing artifact 同样必须携带 task、parent、committed
sequence 和 committed status；E 之后的 future report 不得进入 snapshot。

崩溃恢复遵守固定语义：marker 后、promotion 前崩溃时先补齐 promotion 再冻结
新的 E；部分 promotion 后崩溃时按 publication kind 的稳定 identity 幂等补齐：
bundle 使用 `(task_id, state_key)`，report 使用 `(task_id, report_kind)`，SEC closure
member 使用 `(task_id, artifact_role, semantic_or_content_id)`，最终 index/result 使用
`(task_id, capability, semantic_result_id)`；snapshot
已发布而 case 未发布时，必须复用 `(run_id, C, resolved_plan_hash)` 对应的既有
snapshot 与 E，不得用更晚事件重新选择。同一 identity 出现不同 semantic
snapshot 必须 FAIL_STOP；完全相同视为幂等。已落盘但没有 committed
`artifact.written` 的孤儿 artifact 不可见，恢复时可以重新发布事件。

`policy_version < horizon-policy-v3` 的旧 run 没有 snapshot 时继续使用旧
Registry 重放，不重写历史 artifact。v3 run 缺少、损坏、跨 run、跨 ticker、
resolved-plan hash 不符或含 cutoff 后 evidence 的 snapshot 必须产生 FAIL_STOP
安全壳。Audit 仅显示安全摘要；8-K 原文链接只在用户主动选择 detail 后提供。

`research_policy_version`、`resolved_plan_id` 和 `resolved_plan_hash` 必须作为非
敏感字段持久化在 `run.started` 和 fingerprint document（或一个先于 graph 的
committed plan event）中，不能只藏在 `initial_context_hash`。snapshot 缺失时，
assembler 必须从这个 snapshot 外部凭证判断：v3 及以上 FAIL_STOP，只有 v2 及
以下可走 legacy Registry。

#### 4.3.6 测试与实际验收

自动化必须覆盖：

1. ticker/CIK/name/exchange 一致性和三种 regulatory scope；
2. recent/history 拼接、分页耗尽、预算截断和 amendment；
3. accepted timestamp cutoff 与时区边界；
4. 10-K/10-Q raw HTML、规范化文本、hash 与 8-K metadata-only；
5. User-Agent 缺失、HTTP/网络失败、无 CIK、超限和解析失败；
6. A 股官方 full、双源 partial、后缀-only unavailable 和冲突 FAIL_STOP；
7. snapshot hash、幂等重放、损坏/跨 run/跨 ticker/post-cutoff 拒绝；
8. US SEC medium/long 的 full 可达、非 SEC Global 保持 limited；
9. pre-change ResearchCase Reader golden 仍可打开。

此外必须包含以下 silent-failure 断言：

- missing User-Agent、cutoff failure 和 unresolved scope 均为零 SEC HTTP 调用；
- User-Agent canary 不出现在 effective config、fingerprint、events、artifacts、
  cache key、logs 或异常中；
- incomplete-history + zero target、8-K-only、missing/invalid accepted timestamp、
  recent/history duplicate conflict 和 post-cutoff amendment；
- exhaustive history + all targets rejected for invalid accepted timestamp，必须
  生成 partial/zero-item 而不是 not_covered；
- malformed/missing history manifest ranges、America/New_York DST 转换，以及同日
  市场收盘前/后的 cutoff；
- fake-clock 下的并发限速、429 cooldown、oversize 和 parser timeout；
- raw/index/bundle/snapshot/case 每个崩溃点、未来事件注入和 through-sequence replay；
- v2 legacy 无 snapshot 可重放，v3 无 snapshot 必须 FAIL_STOP；
- E2E 必须断言 artifact/event/provenance linkage，不只检查 Reader 文案。

生产 E2E fake runner 不再发布 Buy/Hold/Sell、仓位和旧 public-output 模板；它
必须发布 typed identity/capability results、SEC available/provider outage 两种
确定性场景、PIT snapshot、`research-case-v2` 和 Audit capability summaries。
浏览器验收覆盖创建运行、SSE、Reader、Audit、刷新重放、控制台和初始 DOM
隐私；Computer Use 只补充真实窗口、滚动和长内容检查。真实 SEC 是可选 smoke，
不是自动化完成 oracle。

完成要求是新增定向门禁全部通过，且完整套件不新增未解释失败；现有失败仍须
单列，不能误报为全绿。

### 4.4 实施计划（In Progress）

本节把 4.3 的已批准设计拆成可独立验收的实施故事。完成状态表示对应内部契约
已在本演进分支实现并通过门禁，不表示 production v3 已启用。实施默认 WIP=1，按编号
逐个完成；每个故事先写失败测试，再写最小实现，再运行相关回归并单独提交。
不新增规格、进度或 handoff Markdown，状态与验收只更新本文。

#### 4.4.1 任务板、优先级与范围

| ID | Story | Points | 依赖 | MoSCoW | 状态 |
|---|---|---:|---|---|---|
| S1 | 冻结内部契约与 SEC coverage 语义 | 5 | 无 | Must | Done |
| S2a | 实现纯 preflight、cutoff 与 runtime scaffold | 5 | S1 | Must | Done |
| S3 | 建立合规且不可泄密的 SEC transport | 5 | S1 | Must | Next |
| S4 | 构建 SEC filing discovery draft | 8 | S1、S3 | Must | To Do |
| S5a | 规范化并 stage SEC source artifacts | 8 | S3、S4 | Must | To Do |
| S5b | 发布 SEC durable closure 与最终 index | 8 | S5a | Must | To Do |
| S6a | 收紧 A 股与 Global verified identity | 8 | S1、S2a、S4 | Must | To Do |
| S6b | 冻结 scope、resolved plan 与授权后事件 | 8 | S2a、S3、S6a | Must | To Do |
| S7a | 闭合 policy、eligibility 与最终 stance | 8 | S5b、S6b | Must | To Do |
| S7b | 让 graph 只消费 frozen required plan | 5 | S6b、S7a | Must | To Do |
| S8a | 构建 bounded Registry 与纯 snapshot builder | 8 | S5b、S7a | Must | To Do |
| S8b | 建立发布屏障、恢复语义并原子启用 v3 | 8 | S7b、S8a | Must | To Do |
| S9 | 迁移生产 E2E fixture 与实际 Reader 验收 | 5 | S8b | Must | To Do |
| S10 | 合入 CI、隐私门禁与统一文档收尾 | 5 | S1-S9 | Must | To Do |

本切片的 Should Have 只有显式配置身份后的真实 SEC 只读 smoke；它不是自动化
oracle，也不能阻止无网络环境完成确定性验收。其他监管机构、8-K 正文批量解析、
Reader schema/layout 变化、跨模型适配、交易信号、仓位、回测和 P&L 学习均为
Won't Have。

当前工作区已有用户自己的 Reader、静态产物与 `research_manager.py` 未提交修改。
实现前后都必须重新核对 Git 状态，不得暂存或覆盖这些修改。这一保护适用于所有
story；任何可能重写 `tradingagents/web/static/` 的 production build、E2E server
或实际浏览器验收必须在 `/private/tmp` 的独立 clean worktree 执行。若确实必须在
当前工作区执行或改动用户已修改的 `research_manager.py`，先停止并取得逐文件
授权，不自行合并。

跨故事硬规则：S8b 原子激活前，所有新增运行行为只允许由显式 v3 test gate
启用，production fresh run 继续 v2。任何 story 只要触及现有 runtime、通用 parser、
publisher、AgentState、provider 或 replay 路径，就必须在该 story 内通过 v2
fresh-run 与 replay golden；不能把兼容验证推迟到 S8b。

#### 4.4.2 S1：冻结内部契约与 SEC coverage 语义

**作为** Research Case 管线，**我希望** identity、SEC filing 和 snapshot 拥有
严格版本化契约，**从而** provider、Registry 和 eligibility 不再靠松散字典猜测。

Acceptance criteria：

- Given 相同规范化输入，When 构建 identity、filing index/document、typed result
  或 snapshot，Then semantic ID/hash 稳定且字段顺序不影响结果；
- Given incomplete search、rejected target、exhaustive zero target 和 8-K-only
  四类输入，When 映射 generic coverage，Then 结果严格符合 4.3.4，非法零项组合
  在模型验证阶段失败；
- Given identity subclass payload，When publisher、Registry 或任何 generic result
  入口解析，Then统一 discriminated parser 保留 subclass 字段；未知 contract kind
  fail closed，而不是被 `CapabilityResultV1(extra=forbid)` 误拒绝或降级；
- Given contract payload 含未知字段、跨 ticker 引用或 hash 不符，When 校验，
  Then fail closed，不做兼容性静默丢字段。

Tasks / technical notes：

- 新增 `tradingagents/research/instrument_identity.py`、
  `tradingagents/research/sec_filings.py` 和
  `tradingagents/research/pit_snapshot.py` 的纯模型与 canonical helpers；
- 在 `tradingagents/dataflows/coverage.py` 增加 SEC 专用 validator 和最小兼容投影，
  不放宽其他 capability 的零项不变量；
- 扩展 `capability_result.py` 的 identity typed result 和统一 discriminated
  parser/union；同步替换 publisher、Registry coverage/result 等全部基类解析入口，
  所有派生字段进入 semantic ID；
- 新增纯契约测试，并在 `.gitignore` 明确放行对应测试文件。

Estimation：5 points。依赖：无。Business value：High。

实现状态：完成。identity、SEC filing/index、PIT snapshot、SEC coverage 与 typed
result parser 已形成严格 v1 内部契约；新增 durable ref 统一使用内容寻址 ID，
Registry/publisher 对跨 ticker、未知 subtype、half-typed wrapper、hash/closure 不一致
均 fail closed。冻结的 pre-S1 v2 fixture 已验证 Registry、Research Case 与 Reader
纯读 replay 不写回。Pydantic 2.11.7 与 2.13.3 聚焦测试均通过；CI 后端契约
109/109 通过；完整后端为 1738 passed、28 failed、68 subtests passed，28 项失败
与实施前基线数量一致且不在 S1 修改路径。

#### 4.4.3 S2a：实现纯 preflight、cutoff 与 runtime scaffold

**作为** 历史公司研究使用者，**我希望** preflight 与 cutoff 可以无副作用地冻结，
**从而** 后续 identity、policy 和 resume 能建立在同一可测试的时间基础上。

Acceptance criteria：

- Given 过去、市场本地当天盘前/盘中/盘后和未来日期，When 解析 cutoff，Then
  分别使用市场 EOD、`min(EOD, captured_at)` 或 invalid，结果可用 fake clock
  重放；
- Given相同 request 与 injected clock，When resume preflight 和真实执行分别解析，
  Then得到相同 prepared scaffold，不写事件、不访问 provider；
- Given显式 v3 test gate 下 scaffold 字段变化，When构建 fingerprint，Then
  preflight/cutoff schema 参与兼容性判断；production v2 fingerprint projection 保持
  原样，不要求新字段或 snapshot；
- Given任何本故事共享路径改动，When重放现有 v2 golden，Then历史 artifact 不被
  重写，旧 run 不需要新增字段。
- Given后续 v3 fields 加入 AgentState，When选择 schema descriptor，Then v2 运行与
  checkpoint 继续使用冻结的 legacy descriptor/hash，v3 才使用包含新字段的
  descriptor；不能由全局最新 TypedDict hash 隐式改变 v2 fingerprint。

Tasks / technical notes：

- 演进 `analysis_cutoff.py`、`execution/runner.py`、`runtime/fingerprint.py` 和
  prepared-context schema；只建立可注入 identity/plan 槽位，不在本故事接入 provider；
- 在 `observability/canonical.py` 与 fingerprint boundary 定义按 policy version
  选择的 AgentState schema descriptor；v2 descriptor 固定，v3 descriptor 可演进，
  observation commit 与 resume comparison 使用同一个已选 descriptor；
- `_resolve_initial_context` 保持纯函数式边界；本故事不发布 plan event，不升级
  production policy，event 与 frozen plan 接线留给 S6b；
- 为同日 cutoff、future invalid、双次纯解析与 v2 resume golden 建立测试。

Estimation：5 points。依赖：S1。Business value：High。

实现状态：完成。production v2 继续使用字面量冻结的 41 字段 descriptor 与原有
fingerprint 投影；显式内部 v3 test gate 使用完全注入的 clock、identity preflight、
past context 与 instrument context，缺一即 fail closed，不回退到 memory/provider。
bounded cutoff 已覆盖 A 股和纽约时区的历史、市场本地当天及未来日期；`captured_at`
只属于调用 envelope，不进入 semantic scaffold。run-scoped policy 已贯穿 fingerprint、
observation candidate/commit、checkpoint projection 与 reconciliation，跨 policy token
稳定报 `commit_token_schema`。聚焦门禁已加入 CI；production v3、真实 identity/plan
provider 与 plan event 仍保持未激活，分别留给 S6a/S6b。

#### 4.4.4 S3：建立合规且不可泄密的 SEC transport

**作为** 数据完整性维护者，**我希望** SEC 访问有明确身份、限速、预算与脱敏，
**从而** provider failure 可诊断但访问身份不会进入任何持久化表面。

Acceptance criteria：

- Given `TRADINGAGENTS_SEC_USER_AGENT` 缺失，When 调用任何 SEC capability，Then
  返回 `provider_unavailable/sec_user_agent_not_configured` 且 HTTP 调用数为 0；
- Given canary User-Agent，When 运行成功或失败，Then canary 不出现在 effective
  config、fingerprint、event、artifact、cache key、log、异常、本系统对外 API
  响应、请求日志或调试投影，只出现 `configured: true`；唯一允许表面是发往 SEC
  host 的 outbound `User-Agent` header；
- Given fake clock 下并发请求，When 命中 token bucket 或 429，Then 每 host 不超过
  5 rps、并发不超过 2，并尊重 `Retry-After` cooldown；
- Given 403、5xx、timeout、非法 content type 或超限文档，When transport 返回，
  Then 使用稳定 reason code，不紧密重试，不返回截断 bytes。

Tasks / technical notes：

- 新增 `tradingagents/dataflows/sec_edgar.py`，注入 clock、HTTP client 和 budget，
  transport 私有读取环境变量并提供只返回 boolean 的 config-status resolver；
- 扩展 `observability/redaction.py`，把 `user_agent`、`sec_user_agent` 及规范化变体
  纳入统一敏感键注册；
- `.env.example` 只说明配置方法，不写真实身份；默认 config 不保存原值。

Estimation：5 points。依赖：S1。Business value：High。

#### 4.4.5 S4：构建 SEC filing discovery draft

**作为** 历史公司研究使用者，**我希望** discovery draft 保留 cutoff 前已验证的
usable targets 与真实搜索完成度，**从而** 后续 Agent 不会看到未来 amendment，
也不会因漏页把 partial 误判成“没有披露”。

Acceptance criteria：

- Given ticker map、recent 和多个 history fixtures，When discovery，Then 只保留
  精确 forms，解析 New York DST accepted time，并在 cutoff 后排除；
- Given recent/history 同 accession 相同或关键字段冲突，When merge，Then 前者
  幂等去重，后者 invalid/FAIL_STOP；
- Given history manifest 范围缺失或非法，When 预算足够或不足，Then 分别保守读取
  内容或明确 partial，不能跳过并声称 exhaustive；
- Given accepted timestamp 缺失/非法，When target 被拒绝，Then增加
  `rejected_target_count`，即使所有 target 被拒绝也返回 partial zero-item，而非
  not_covered；
- Given history search 不完整但已有 usable target，When 生成 draft，Then保留该
  target 且 coverage 为 partial；S4 不发布最终 durable index/result；
- Given 健康 ticker map 无 CIK、完整窗口无目标 forms 或 provider outage，When
  构建 discovery outcome，Then保留足以让 S5b 唯一生成规定 not_covered 或
  provider_unavailable typed result 的结构化原因。

Tasks / technical notes：

- 在 `sec_filings.py` 实现 ticker/CIK/name/exchange binding、recent/history parser、
  accession merge、cutoff filter 与纯 `SecFilingDiscoveryDraftV1` builder；
- discovery 只依赖 S3 注入 transport，不在 parser 中读环境、系统时钟或网络；
- 使用脱敏 SEC JSON fixtures 覆盖 current/history、amendment 与 DST 边界。

Estimation：8 points。依赖：S1、S3。Business value：High。

#### 4.4.6 S5a：规范化并 stage SEC source artifacts

**作为** 证据审计者，**我希望** SEC source JSON、10-K/10-Q 原文和规范化文本
形成可 checkpoint 的 staged closure，**从而** parser 与 transport 不需要直接
依赖运行存储，恢复后仍能证明每个文件属于哪个 graph task。

Acceptance criteria：

- Given `10-K`、`10-K/A`、`10-Q`、`10-Q/A`，When 下载成功，Then完整 raw bytes
  与规范化文本分别形成 content-addressed staged artifact refs；
- Given current submissions 与每个实际读取的 history JSON，When discovery 完成，
  Then每个完整 source payload 都有 staged ref，draft 不只留下远端 URL；
- Given 8-K/8-K-A，When staging，Then只保留完整 metadata 与 SEC 原文链接，不下载
  正文；
- Given parser timeout、oversize、非法 content type 或字符集异常，When 处理，
  Then不保存截断正文，已完整冻结的 raw artifact 保留，结果按规则 partial；
- Given graph candidate delta，When checkpoint 持久化，Then closure manifest 含
  opaque staged refs、run/ticker/task/hash/role，恢复时不需要重新下载已完整内容。
- Given v3 maintenance node 在 observed task context 内或外执行，When获取 artifact
  sink，Then前者得到绑定 observer/run/task/graph-step 的窄 sink，后者 fail closed；
  v2 节点继续原路径，不要求 sink。

Tasks / technical notes：

- 增加窄接口 `EvidenceArtifactSink`，包装现有 `RunStore.store_artifact` 并返回
  `StagedArtifactRefV1`；transport/parser 不直接导入 RunStore；
- 由 `ObservedGraphTask` 调用 maintenance node 时建立 run-scoped sink context，
  producer 只通过窄 context accessor 获取；必要落点包括 `graph_tasks.py` 和 graph
  runtime，禁止 provider 从全局查找 store；
- staged refs 与 closure manifest 必须进入 AgentState/candidate delta，只有后续
  parent commit promotion 才使其对 Registry 可见；不重写现有原子存储实现；
- 规范化固定为确定性 charset、script/style 移除、Unicode NFC 与空白归一化，
  预算严格使用 5s connect、30s read、10s parser、20 MiB。

Estimation：8 points。依赖：S3、S4。Business value：High。

#### 4.4.7 S5b：发布 SEC durable closure 与最终 index

**作为** Evidence Registry，**我希望** 只看到 checkpoint 后校验并提交的完整 SEC
closure，**从而** staged 文件或不完整 draft 不能被误当作可引用证据。

Acceptance criteria：

- Given staged current/history JSON、必要 raw/normalized documents 和 discovery
  draft，When parent graph commit 被接受，Then publisher 先验证 run、ticker、task、
  hash 与 closure，再发布 visibility events、最终 `SecFilingIndexV1` 和 typed result；
- Given final index，When递归检查 `source_artifacts` 与 document refs，Then每个读取的
  current/history JSON 及每个必要正文均可由 committed event、hash 和 lineage 找到；
- Given仅有 8-K/8-K-A 且 metadata/index 完整，When构建结果，Then无需正文即可
  available；Given 任一必要 10-K/10-Q 文档缺失，Then至多 partial；
- Given orphan staged file、closure hash 不符或跨 run/ticker ref，When publisher
  处理，Then拒绝发布；未提交 orphan 对 Registry 不可见；
- Given现有 v2 run/golden，When共享 publisher 与 Registry 路径变化，Then历史
  artifact 仍可重放且不要求 snapshot。

Tasks / technical notes：

- 扩展 `output_publisher.py` 的 SEC closure promotion，复用现有 store，不把可见性
  逻辑放进 transport 或 parser；
- S4 只拥有 discovery draft；最终 index/result 的唯一所有者是本故事；
- 部分 promotion 崩溃与跨 commit 恢复留给 S8b，本故事只证明单次 accepted parent
  下的闭包、顺序与 fail-closed publication。

Estimation：8 points。依赖：S5a。Business value：High。

#### 4.4.8 S6a：收紧 A 股与 Global verified identity

**作为** 公司研究使用者，**我希望** 公司身份的 full/partial/invalid 有字段级
来源证明，**从而** ticker 后缀或 provider failure 不会被误当成公司事实。

Acceptance criteria：

- Given CNINFO/交易所确认 ticker、名称、证券类型和历史上市状态，When 截止日
  有效，Then identity verification 为 full；
- Given 官方源不可用且 Tushare 与 EastMoney/AKShare 两个独立来源逐字段一致，
  When 合并，Then verification 仅为 partial，eligibility 至多 limited；
- Given suffix-only、单一第三方源或缺失 effective time，When 验证，Then分别为
  unavailable 或至多 partial，不推导上市状态；
- Given 两个成功观测来源在关键字段冲突，When 合并，Then invalid/FAIL_STOP；
  provider failure 只进入 attempts，不制造冲突事实；
- Given US ticker map 只能证明当前身份，When cutoff 是历史日期，Then必须由 cutoff
  前 filing metadata/header 绑定，否则至多 partial。
- Given `global_non_sec` 当前或历史 fixture，When官方身份字段完整或只能证明当前
  状态，Then分别按证据得到 full 或至多 partial；不得为未实现监管披露生成 SEC
  coverage。

Tasks / technical notes：

- 将现有 identity producer 演进为字段 facts + attempts，复用严格 official source
  路由并保持 EastMoney 不得伪装交易所；
- capability result 与 coverage 分别保存 availability 与 verification_level，不
  互相推导；eligibility 强制规则留给 S7a；
- 所有 provider 测试使用 fixture，真实第三方网络不是完成条件。

Estimation：8 points。依赖：S1、S2a、S4。Business value：High。

#### 4.4.9 S6b：冻结 scope、resolved plan 与授权后事件

**作为** 可恢复运行，**我希望** verified identity、监管 scope、SEC 配置状态与
resolved plan 在授权后、graph/prefetch provider 前只冻结和发布一次，**从而** 被拒绝的
resume 不污染事件流，真实执行也不会与 preflight 产生两个计划。

Acceptance criteria：

- Given无冲突美国、非美国、缺失或冲突身份 facts，When结合 preflight 与 S6a
  identity，Then只得到 `us_sec_candidate`、`global_non_sec` 或 `unresolved`；
- Given unresolved scope 或 cutoff invalid，When运行，Then在任何 SEC HTTP 前停止；
- Given相同 prepared context，When fresh run、resume preflight 与授权后执行，Then
  plan ID/hash 和 fingerprint 一致，纯解析阶段不写事件；
- Given显式 v3 test gate 且 fingerprint authorization 成功，When graph 尚未启动，
  Then幂等发布一次
  committed verified identity artifact/result 与 `research.plan_resolved`；后者包含
  非敏感 policy schema、identity ref、scope、cutoff、plan ID/hash 与 SEC configured
  boolean；
- Given resume authorization 失败或 preflight 被重复调用，When检查事件流，Then无
  plan event 污染或重复；现有 v2 golden 仍可重放且不要求 snapshot。
- Given v3 fresh run，When准备 context，Then先纯解析/stage identity，再冻结
  plan/fingerprint，授权成功后发布；Given v3 resume，Then Manager 在 preauthorize
  前从既有 committed `research.plan_resolved` hydrate identity/plan，既不重调
  identity provider，真实执行也复用同一 contract；
- Given committed plan，When identity artifact 对 Registry 可见，Then
  `research.plan_resolved` 是 run-level `pregraph-plan` commit marker，identity
  artifact event 以它为 parent 并携带其 sequence；不得伪装 graph-task lineage。

Tasks / technical notes：

- 演进 `horizon_policy.py`、runner、fingerprint、event schema、redaction/projection、
  AgentState 与 propagation；event 幂等键绑定 run + plan hash；
- 顺序固定为 pure resolve/freeze → fingerprint authorization → committed plan event
  → graph/prefetch provider；`run.started` 保持 Manager 现有生命周期；
- fresh 与 resume 使用两个显式分支；v3 resume 缺失、重复或损坏 plan marker 时在
  provider/graph 前拒绝，Registry validator 支持 `pregraph-plan` 与 `graph-commit`
  两种且仅两种 lineage；
- 构建 `ResolvedDataWindowPlanV3` 和测试 gate，但 production policy 继续为 v2；
  v3 默认激活与 snapshot 缺失保护必须在 S8b 同一原子故事完成。

Estimation：8 points。依赖：S2a、S3、S6a。Business value：High。

#### 4.4.10 S7a：闭合 policy、eligibility 与最终 stance

**作为** 学习型研究系统，**我希望** required evidence 由冻结 policy 驱动且不能
被 analyst 选择或 favorable 文本绕过，**从而** full 始终表示证据契约真正闭合。

Acceptance criteria：

- Given A 股、US SEC、非 SEC Global 的 short/medium/long 矩阵，When required
  evidence 完整或缺失，Then full/limited/FAIL_STOP 与 policy v3 唯一对应；
- Given US candidate medium/long，When SEC evidence 完整，Then
  `sec.company_filings` 可满足 required official；When UA 缺失/outage，Then scope
  不改变但只能 limited；
- Given non-SEC Global medium/long，When运行，Then返回
  `not_supported/regulatory_provider_not_implemented`，第三方新闻不能替代；
- Given required typed result 为 0 个或多个，或 semantic ID/plan/ticker/date 自相
  矛盾，When eligibility，Then属于 contract integrity failure 并 FAIL_STOP；
- Given合法 result 为 partial/stale，When eligibility，Then至多 limited；Given
  `not_covered`、`not_supported` 或 `provider_unavailable`，Then limited 且顶层
  `insufficient_evidence`；Given `invalid`，Then FAIL_STOP；
- Given result 声称 current 但时间 facts 不支持，When校验，Then FAIL_STOP；正常且
  自洽的 stale value 不是 integrity failure；Given identity 非 full，Then不能 full；
- Given任一 required capability 为 not_covered、not_supported 或
  provider_unavailable，When模型 draft 给出 favorable stance，Then case assembler
  最终政策覆盖层强制 `insufficient_evidence`；Given invalid，Then FAIL_STOP；
- Given共享 Registry/assembler/eligibility 路径变更，When重放现有 v2 golden，Then
  legacy case 仍可打开，不要求 typed v3 result 或 snapshot。

Tasks / technical notes：

- 演进 `official_disclosures.py`、Registry、claim capability policy、case assembler
  与 eligibility；
- 强制 required typed result，保留 v2 legacy replay 但不得让 legacy fallback
  满足 v3；
- 用一张参数化矩阵测试覆盖九个 market-scope × horizon 组合与 failure states。

Estimation：8 points。依赖：S5b、S6b。Business value：High。

#### 4.4.11 S7b：让 graph 只消费 frozen required plan

**作为** policy owner，**我希望** maintenance producer 由 frozen required
capabilities 驱动，**从而** 用户是否选择某个 analyst 不会决定必要证据是否被获取。

Acceptance criteria：

- Given任意 analyst selection，When frozen plan 要求 identity、snapshot、price、
  event、official 或 fundamentals，Then对应 maintenance nodes 都存在且顺序稳定；
- Given A 股 supplement，When news/fundamentals analyst 未选择，Then required official
  或 fundamentals producer 仍执行，不沿用 analyst-key 条件；
- Given v3 prepared state，When graph nodes 执行，Then price、news、fundamentals、
  official 与工具节点不再调用 `build_data_window_plan` 重建 policy；
- Given production 默认仍是 v2，When旧请求运行，Then graph 兼容路径和 v2 golden
  不改变；显式 v3 fixture 才走 frozen plan。

Tasks / technical notes：

- 枚举并替换 market data、news、fundamentals、official disclosure 与工具节点中的
  plan 重建调用点；
- graph setup 从 frozen required capabilities 构造 maintenance chain，analyst 选择
  只决定解释角色，不决定 evidence producers；
- 为 analyst 组合、九格 policy 与 v2/v3 分流建立参数化测试。

Estimation：5 points。依赖：S6b、S7a。Business value：High。

#### 4.4.12 S8a：构建 bounded Registry 与纯 snapshot builder

**作为** Research Case 的所有 Agent，**我希望** 引用同一个已冻结 snapshot，
**从而** 组装、刷新和恢复都不会重新挑选更有利或更晚的证据。

Acceptance criteria：

- Given显式 C 与 E，When Registry 读取 `read_events(through=E)`，Then只选择
  committed status、parent/task lineage 和 `committed_sequence <= C` 合法的 bundle、
  SEC closure 与 report evidence；
- Given verified identity 或 graph evidence，When验证 lineage，Then前者只接受
  `pregraph-plan` marker，后者只接受 `graph-commit` marker；两类不能相互冒充；
- Given缺失/伪造 committed sequence、错误 parent/task、未来事件、跨 run/ticker、
  post-cutoff 或 closure/hash 损坏，When 构建/重放，Then FAIL_STOP；
- Given同一 run 的 replay、相同 C 和相同可见事件，When纯 snapshot builder 重复
  构建，Then semantic hash 和 selections 相同，E 不参与 semantic hash；
- Given report 在 E 前合法发布或 E 后才发布，When构建 snapshot，Then前者可被
  选择，后者被排除；
- Given v2 Registry golden，When bounded/lineage 路径加入，Then legacy 重放仍成功，
  不要求 v3 committed metadata 或 snapshot。

Tasks / technical notes：

- 为 EvidenceRegistry 增加显式 `through`、source boundary 与 lineage validator，
  删除 v3 的 `committed_sequence=0` 默认；
- 实现无副作用 snapshot builder 与 artifact closure validator；assembler 增加消费
  frozen selections 的内部入口，但 production publication 仍不切到 v3；
- 纯测试覆盖 bundle、SEC closure、report、future injection 和 hash/closure 错误。

Estimation：8 points。依赖：S5b、S7a。Business value：High。

#### 4.4.13 S8b：建立发布屏障、恢复语义并原子启用 v3

**作为** 可恢复 Research Case publisher，**我希望** 所有 Registry-visible evidence
先发布、冻结 E、再发布 snapshot 与 case，**从而** 任一崩溃点恢复后都不会漏选、
重复选择或重新挑选未来证据。

Acceptance criteria：

- Given一批 accepted graph commits，When promotion，Then先发布全部 bundle、SEC
  closure、`report.updated` 及 backing artifacts，再冻结 durable event boundary E，
  然后仅在存在 case candidate 时构建/复用 snapshot，最后发布 case；
- Given v3 report publication，When写入事件，Then report 与 backing artifact 都有
  committed status、task、parent 与 committed sequence；E 后 future report 被排除；
- Given marker 后、部分 promotion 后、snapshot 后或 case 前崩溃，When resume，Then
  分别补齐幂等 publication、复用既有 `(run_id,C,plan_hash)` snapshot/E，且不漏不重；
- Given bundle、report、closure member、final index/result 或 snapshot 任一稳定
  identity 的 partial publication，When crash/retry，Then各自按 4.3.5 的 identity
  幂等补齐，不用其他 kind 的键误判已完成；
- Given同一 snapshot identity 出现不同 semantic snapshot，When恢复，Then
  FAIL_STOP；完全相同视为幂等；
- Given v2 run 无 snapshot 或 v3 run 无/坏 snapshot，When重放，Then前者走 legacy，
  后者安全壳；Reader 公共 schema 保持兼容；
- Given所有 v3 路径通过，When production policy 从 v2 切到 v3，Then activation、
  snapshot 强制与 v2/v3 分流发生在同一提交，不存在“v3 已标记但无 snapshot”窗口。

Tasks / technical notes：

- 重构 `_promote_commits` 为 batch phases，不在逐 commit 循环中提前组装 case；阶段
  次序固定为 Registry-visible publication → E → snapshot → case → lifecycle terminal；
- 给 v3 report publication 补齐 lineage metadata，publisher 冻结真实 event-log E，
  不把 payload 的 committed sequence 当作物理边界；
- 实现 crash injection、resume reuse、v2/v3 分流与最终 policy activation 测试。
- activation 同步选择 v3 AgentState schema descriptor；v2 fresh/replay/resume 继续
  使用冻结 legacy descriptor，不用全局最新 schema hash 改写历史边界。

Estimation：8 points。依赖：S7b、S8a。Business value：High。

#### 4.4.14 S9：迁移生产 E2E fixture 与实际 Reader 验收

**作为** 产品维护者，**我希望** 本地真实运行链展示 typed evidence、snapshot 和
Research Case，**从而** E2E 验证的是现役学习产品而不是旧交易模板。

Acceptance criteria：

- Given deterministic SEC available 与 provider outage 场景，When fake runner
  完成，Then发布 identity/result/bundle/snapshot/case 及完整 event/provenance
  linkage，不发布 Buy/Hold/Sell、仓位或旧 public-output；
- Given创建运行、SSE、Reader、Audit 与页面刷新，When使用浏览器自动化，Then
  snapshot-backed case 可重放，capability 摘要一致，控制台无异常；
- Given初始 DOM、网络响应和 Audit detail，When扫描 canary，Then无 User-Agent、
  locator、Prompt、原始 provider 异常或私有思维链；
- Given真实桌面窗口、长内容和窄宽度，When使用 Computer Use，Then关键内容可读、
  滚动与刷新正常，不依赖自动化截图的偶然布局。

Tasks / technical notes：

- 改造 `scripts/e2e_server.py` 和现有 Reader/Audit fixtures；公共 Reader DTO 不变；
- 本故事同步在 `.gitignore` 精确放行 e2e server 与新增 fixture/test，不等待 S10，
  也不使用 `git add -f`；
- 先跑 Playwright/HTTP assertions，再按用户要求用 in-app Browser 与 Computer Use
  做实际交互；server、production build 和实际浏览器测试全部从独立 clean worktree
  启动，真实 SEC 只做可选、只读、明确 UA 的 smoke。

Estimation：5 points。依赖：S8b。Business value：High。

#### 4.4.15 S10：合入 CI、隐私门禁与统一文档收尾

**作为** 后续维护者，**我希望** clean checkout 能复现新增契约和关键失败路径，
**从而** 新 provider 或模型不能悄悄绕过证据闭包。

Acceptance criteria：

- Given clean checkout，When CI 运行，Then contract、cutoff/policy、SEC transport、
  discovery/document、identity、eligibility、snapshot/replay 与 E2E 关键测试均被
  明确跟踪并执行；
- Given完整后端/前端套件，When比较批准前基线，Then不新增未解释失败；目标门禁
  全绿，既有失败继续单列；
- Given最终 Git diff，When closeout，Then只包含本切片授权文件，不包含用户既有
  Reader/静态产物/manager 修改或临时报告；
- Given最终状态，When维护者阅读本文，Then能够区分 Merged、Branch Ready、可选
  smoke 与未实现范围，不需要第二份状态文档。

Tasks / technical notes：

- 精确扩展 `.gitignore` test whitelist 和 `.github/workflows/ci.yml`，禁止
  `git add -f`；
- 运行 Ruff、定向/完整 pytest、Vitest、typecheck、production build、Playwright、
  `git diff --check`，并记录准确基线；任何会生成静态产物的命令只在 clean
  worktree 运行，并把结果与实现 commit 比较；
- 使用 neat-freak 复核 code/runtime/docs/rules/memory/workspace 六个事实表面，
  只更新本文；任何删除候选先报告，取得单独确认后才执行。

Estimation：5 points。依赖：S1-S9。Business value：High。

#### 4.4.16 Definition of Ready、提交顺序与 Definition of Done

Definition of Ready：4.3 设计和双边界勘误已批准；每个 story 的 fixture、clock、
failure reason 与 expected coverage 可在无网络环境表达；开始 story 前工作区与用户
修改边界已重新确认；任何重叠文件已有明确处理方式。

建议提交顺序与故事一致，每个 commit 只跨一个可独立回退的行为边界：contracts；
纯 preflight/cutoff；SEC transport；filing discovery draft；artifact staging；SEC
durable closure；verified identity；scope/plan persistence；policy/eligibility；
frozen-plan graph；bounded Registry；PIT publication/recovery/v3 activation；E2E；
CI/docs。S4、S5a、S5b 即使由同一模块承载也保持独立提交，使 parser、文件副作用
和可见性 publication 分别审查。

Definition of Done：

- 每个 story 的 Given/When/Then acceptance criteria 有自动化证据；新行为先看到
  失败测试，相关回归、Ruff 和 `git diff --check` 通过；
- v3 required capability 不能缺 typed result，任何 future/cross-run/corrupt/identity
  conflict 都安全降级或 FAIL_STOP，不留下模型可绕过的 favorable rating；
- SEC canary 通过所有持久化、日志、本系统对外 API、cache 和异常表面的负向
  扫描，只允许出现在发往 SEC host 的 outbound header；
- snapshot、case、Audit 与刷新重放拥有可追踪 event/artifact/provenance linkage；
- 完整套件不新增未解释失败，浏览器与 Computer Use 实际验收完成；
- 不更改 Reader 公共 schema，不实现跨模型适配或交易目标，不覆盖用户未提交修改；
- 本文状态更新为 Branch Ready，分支按授权提交并推送；清理动作遵守 neat-freak
  的再次确认门槛。

## 5. 已合入功能的验收记录

本节保留已合入能力的验收边界，便于后续改动定位回归；它不是待办列表或
Reader 路线图。新的能力应以独立变更说明和对应测试进入，而不是在这里追加
过程日志。

### 5.1 P1-7 合入前硬化与文档整合（Merged）

**目标：** 先补齐可复现验证与发布边界，再让 `main` 拥有稳定的跨 Run
论点比较和唯一文档入口。

已完成：

- `2f818bf` 的生产实现完整保留；
- 为基线选择、五态转移、invalidated 反证守卫、Reader 投影和 HTTP 响应
  建立可从普通 branch checkout 运行的测试；
- 明确调整 `/tests/` ignore 策略或采用受 Git 跟踪的测试位置，不再把
  local-only tests 当作合入证明；
- post-completion 发布具备稳定 provenance 和事件级幂等测试；
- 恢复 `2f818bf` 误覆盖的 `_finish_cancelled` 方法边界，并把成功收尾收窄为
  只终结 pending/skipped roles，不掩盖真正 running 的角色；
- 本文进入 Git，旧重复文档删除；
- README 只指向本文，不再描述学习路径为 Buy/Sell 管线；
- 仓库不再维护 `CLAUDE.md`，README 不保留对它的引用；
- P1-7 目标回归、Ruff、前端 typecheck/build 和 `git diff --check` 通过；后端
  完整本地套件的既有失败已在第 6 节单独记录。

### 5.2 P2-2：学习报告与论点变化（5 points，Merged）

**As a** 重复研究同一公司的读者  
**I want** 在研究正文中看到本轮论点相对上一基线的变化  
**So that** 我能区分新信息、持续假设、反证和未复核内容。

已完成：

- 前端契约不再把 `thesis_diff` 固定为 null；
- 五种 diff kind 使用独立中文标签和图标，不只依赖颜色；
- `unresolved` 与 `not_reassessed` 文案不同；
- change flags 分别表达文本、证据、置信度和状态变化；
- counter-evidence 只走安全 public ref，不显示 locator/hash/raw；
- fixture 覆盖有基线、无基线和 diff 不可用。

验证：受跟踪的组件 fixture 2/2 通过，前端 typecheck 与 production build
通过并同步静态产物；完整本地 Vitest 为 105 passed、2 failed，两项失败均为
本轮改动前的旧 Controls/App 文案与入口断言。Playwright 已检查桌面和 720px
窄屏，五态概览、前后文本对照及单栏降级均可读。

### 5.3 P2-3a：Companion 公共契约与 API（3 points，Merged）

**As a** Reader 用户  
**I want** 按需查看选中论点、角色、证据或风险的伴读摘要  
**So that** 我无需打开 raw 审计数据也能继续理解结论。

已完成：

- 新增封闭 `CompanionSelection` 与 `CompanionDTO`；
- selection 只接受 role/claim/evidence/risk；
- 所有公开 ID 都验证当前 run 归属；
- typed 404 不回退 raw；
- DTO 只包含摘要、实际覆盖、结论影响和下一验证；
- Reader 默认响应移除 audit refs 和 ThesisDiff 中的 Research Case artifact IDs；
- 对序列化 Reader 和初始 DOM 做递归隐私断言；
- 跨 run、未知 ID、不可公开 ID 和正常选择有契约测试。

验证：Companion + Reader 隐私 + ThesisDiff 相关回归 8/8 通过，Ruff、前端
typecheck 和 production build 通过并同步静态产物；后端完整本地套件为
1540 passed、17 failed，失败集合与 P1-7 基线一致。初始 DOM 隐私 fixture
通过；前端完整本地套件为 106 passed、2 failed，仍是既有 Controls/App 断言。

### 5.4 P2-3b：自适应伴读栏（5 points，Merged）

**As a** Reader 用户
**I want** 从正文中的角色、论点、证据或风险按需打开伴读内容
**So that** 我能继续理解结论，同时保留当前阅读位置和研究上下文。

已完成：

- typed client 与 `useCompanion` 实现成功缓存、请求取消、旧响应隔离和显式重试；
- 角色、论点、证据与风险四类正文入口按公开 ID 映射，催化剂没有误映射为风险；
- `CompanionPanel` 完成临时浮层、固定双列和 modal drawer 三种呈现，并由
  Reader 本地四态状态机编排；
- 桌面键盘、焦点返回、跨 1400px 缩放、滚动位置保持和 reduced-motion 已收口；
- 初始页面和空 selection 零预取，typed 404 与普通错误都不回退 raw 数据。

#### 组件与状态边界

- `useCompanion(runId, selection)` 负责按 `(run_id, kind, id)` 缓存、取消过时
  请求、阻止旧响应覆盖新 selection，并提供当前 selection 的重试；
- `CompanionPanel` 只展示 selection、加载/错误状态和 `CompanionDTO`，不直接
  访问 API；
- `TypedSurface` 是唯一交互编排者，持有当前 selection、固定状态和最近一次
  触发入口；切换 run 时整体清空；
- 论点、失效条件和分析视角通过显式“查看伴读”按钮提交统一 selection；证据
  通过安全 `source_label` 标签提交，不显示内部 `ref_id`；催化剂不映射为 risk；
- selection ID 显式映射为 `role → AnalystCard.lens`、
  `claim → PublicClaim.claim_key`、`evidence → ReaderEvidenceRef.ref_id` 和
  `risk → invalidation_conditions[].item_id`；不得使用显示文案或数组下标代替；
- typed client 新增 `getCompanion`，只调用 Companion API，不访问 artifact/raw
  接口。

#### 交互与布局

- 视口宽度不小于 1400px 时，首次选择打开不挤压正文的右侧临时浮层；用户
  主动固定后才切换为正文 + 伴读栏双列布局；固定栏位不锁定内容；
- 1400px 以下统一使用右侧覆盖式 drawer，不显示固定操作；本阶段主要适配
  14 英寸 Mac 和外接显示器，极窄宽度只保证不溢出和基本可操作性，不增加
  单独的手机底部 sheet；
- 临时打开、固定、替换 selection 和关闭都不改变正文滚动位置；关闭后焦点
  返回最近一次触发入口，切换 run 时不把焦点送回旧 run；
- 显示状态显式建模为 `closed | temporary | pinned | drawer`：宽屏选择从
  `closed` 进入 `temporary`，固定后进入 `pinned`；窄屏选择直接进入 `drawer`；
- `temporary` 和 `pinned` 使用非模态 `aside`，不抢走入口焦点、不约束正文
  焦点；固定操作后焦点保留在固定控制上；两种状态下 `Escape` 都关闭面板并
  把焦点返回最近一次触发入口；
- `drawer` 使用 modal dialog 语义，打开后焦点进入关闭控制并约束在面板内；
  `Escape` 关闭并返回触发入口；
- 打开状态从不小于 1400px 缩至小于 1400px 时统一转换为 `drawer` 并清除固定
  偏好；再次放宽只转换为 `temporary`，不自动恢复固定；转换过程保留 selection、
  正文滚动位置和有效焦点；`closed` 在缩放时保持关闭；
- 动画只使用短距离透明度/位移，`prefers-reduced-motion` 下禁用位移和过渡。

#### 数据与错误边界

- 初始 Reader 和空 selection 都不得请求 Companion 或 raw 数据；
- 只有成功校验的 `CompanionDTO` 写入内存缓存；失败和已取消请求不得缓存；
  相同 selection 在当前 run 的页面会话中命中缓存；刷新不恢复 selection、缓存
  或固定状态；
- selection 改变、面板关闭或 run 切换都取消当前进行中的请求；取消不显示错误；
  run 切换同时清空 selection、缓存、错误和固定状态；
- 加载状态保留稳定面板骨架；typed 404 显示安全的不可用文案且不回退 raw；
  其他网络错误提供只针对当前 selection key 的重试，且每次重试创建新请求；
- 成功面板只展示 selection、摘要、实际覆盖、结论影响和下一验证，不扩展
  P2-3a 的封闭 DTO。

#### 验收

- Hook 测试覆盖零预取、只缓存成功结果、取消不报错、旧响应隔离、关闭/run
  切换取消与清理，以及当前 key 的全新重试；
- 组件测试覆盖四类入口、加载/成功/typed 404/普通错误、固定、关闭、
  `Escape`、四态转换、跨 1400px 缩放、焦点返回和初始 DOM 隐私；
- 浏览器验收使用 1512px 检查临时浮层与固定双列，使用 1200px 检查覆盖式
  drawer 和无固定按钮，并验证滚动位置与 reduced-motion；
- 前端定向 Vitest、typecheck、production build 与静态产物同步通过；P2-3a
  后端契约回归保持通过。

验证：Companion API client、Hook、Reader 交互、隐私与 ThesisDiff 定向回归
12/12 通过，P2-3a/P2-2 后端回归 8/8 通过，前端 typecheck、production build
和 `git diff --check` 通过并同步静态产物。Playwright 在 1512×982 验证临时浮层
与固定双列，在 1200×900 验证 modal drawer、焦点约束、`Escape` 返回入口和无固定
按钮；打开、固定和关闭前后正文滚动位置不变，reduced-motion 下无动画，相同
selection 重复打开只产生一次 Companion 请求。完整本地 Vitest 为 115 passed、
2 failed，仍是既有 Controls/App 文案与入口断言。

### 5.5 P2-4：独立 Audit Center（5 points，Merged）

**As a** 需要核验研究过程的 Reader 用户
**I want** 在独立工作区中按需检查运行、角色、能力、工具和持久化材料
**So that** 我能追溯结论依据，又不会在默认阅读路径中提前加载 raw 审计数据。

#### 产品边界

- 新 Audit Center 替换终态运行中的旧 `AuditReader`，覆盖 completed、failed、
  cancelled、interrupted 和 legacy；实时运行的 `Inspector` 保留，并将入口文案
  明确为“实时审计栏”；
- Decision Brief、Reader 审计计数摘要和 Stage Detail 的既有入口统一打开同一个
  Audit Center；从 Reader 到中心不超过两步；
- legacy 继续使用同一工作区并保留阶段导航；缺少结构化事件或关联关系时明确显示
  “历史运行未记录”，不伪造数据，也不自动回退完整 raw 报告；
- 完整报告作为 artifact 列表中的“已发布报告”进入统一详情流程，不再拥有自动加载
  的特殊通道；
- P2-4 不重构实时执行监控、事件流、Companion 或 Reader 公共 DTO。

#### 服务端契约与投影

- 新增 `GET /api/runs/{run_id}/audit`，返回封闭 `AuditSummaryDTO`；只在用户打开
  Audit Center 后由前端调用；
- 新增 `GET /api/runs/{run_id}/audit/detail?kind=...&id=...&v=...`，selection 封闭为
  `run | role | capability | tool | artifact | prompt | config | report`；只有用户明确
  选择单项后才调用；`v` 必须等于当前 active summary 的 `source_sequence`；
- `AuditSummaryDTO` 固定字段为 `schema_version=1`、`run_id`、`source_sequence`、
  `availability`、`reason_code`、`run`、`counts`、`sections`、`stage_navigation`、
  `roles`、`capabilities`、`tools`、`artifacts`、`prompts` 和 `configs`；不得增加任意
  后端字段袋；
- summary availability 封闭为 `ready | partial | legacy | unavailable`；每个 section
  的 availability 封闭为 `ready | partial | unavailable | not_recorded`；v1 reason code
  只允许 `projection_failed | terminal_data_incomplete | legacy_event_gap | not_recorded`
  或 null；
- `sections` 固定为 overview、roles、capabilities、tools、artifacts、prompt_config 六项，
  每项只含 `section_id`、`availability`、`reason_code` 与 `item_count`；`counts` 只含
  `stages`、`roles`、`turns`、`model_calls`、`tool_calls`、`artifacts`、`prompts`、
  `configs` 和 `reports`；
- `run` 固定含 `item_id="run"`、状态、ticker、模式、周期、开始/结束时间、耗时、
  模型名和数据质量；
  role item 含 `item_id/actor_id/label/status/turn_count/model_call_count/duration_ms`；
  capability item 含 `item_id/label/status/reason_codes/affected_sections`；tool item 含
  `item_id/tool_name/status/execution_count/cache_status/failure_code`；
- artifact item 含 `item_id/label/artifact_kind/media_type/byte_size/producer_stage/`
  `content_exposure/is_report`；prompt/config item 含 `item_id/label/actor_id/model_call_id/`
  `redaction_status/byte_size` 中适用字段；列表项不返回 locator、文件路径、hash、参数、
  配置值或 raw 内容；
- `stage_navigation` 是 overview 内的导航数据，每项固定含 `stage_id/label/status/`
  `availability/reason_code/related_selections`；status 封闭为 `not_started | running |`
  `completed | failed | cancelled | interrupted | unknown`，availability 封闭为
  `ready | not_recorded`，reason code 只允许 `legacy_event_gap | not_recorded` 或 null；
  每个 related selection 必须指向同一 summary 中已经存在的 role/tool/artifact/prompt/
  config item。legacy 缺少映射时保留阶段条目，使用 `availability=not_recorded`、
  `status=unknown` 和对应 reason code，不生成虚假 selection；
- detail ID 必须从当前 run 的摘要索引解析；未知、跨 run、伪造或不可公开 ID 统一
  返回 typed `audit_item_not_found` 404，不接受 locator、路径或任意 raw URL；
- v1 item ID 映射固定为 `run → "run"`、`role → actor_id`、`capability → capability`
  slug、`tool → tool_call_id`、`artifact/prompt/config/report → artifact_id`；ID 对前端
  视为 opaque，只能从 summary 取得，report 必须同时是 summary 中 `is_report=true`
  的 artifact；
- `AuditDetailDTO` 公共字段固定为 `schema_version=1/run_id/source_sequence/selection/`
  `availability/reason_code/title/facts/related_selections/content`；availability 封闭为
  `ready | unavailable`，reason code 只允许 `not_recorded | unsupported_artifact |`
  `content_too_large | content_sensitive | detail_not_available` 或 null；
- `facts` 是经过各 kind allowlist 生成的 label/value 对；`content.mode` 封闭为
  `none | inline | download`，并按 mode 只允许 `text` 或 `download_url`，同时携带
  `media_type/byte_size/redaction_status`；非法 kind、缺失或超长 id 走现有
  `validation_error` 422，合法但不可解析的 selection 才是 typed 404；
- detail 结果组合只有五种：结构化详情为 `ready + null + none`；安全内联为
  `ready + null + inline`；超阈值下载为 `ready + content_too_large + download`；已知但
  不支持内联的类型为 `ready + unsupported_artifact + download`；未记录、敏感或没有
  详情分别为 `unavailable + not_recorded/content_sensitive/detail_not_available + none`。
  其他 availability/reason/content 组合视为服务端契约错误，前端不得猜测降级；
- summary 投影只读取当前 run 已持久化的 snapshot、events 与 artifact metadata；
  detail 投影才允许在 selection 通过当前 summary 索引、kind 和敏感度校验后，从同一
  run 的 artifact store 读取被选中的单项内容；两者都不得调用模型、数据供应商或
  其他 run；
- API 只接受 terminal run；pending/running/cancel_requested 统一返回 typed
  `audit_terminal_required` 409，避免与实时 `Inspector` 重叠；summary 投影失败返回
  `availability=unavailable` 的安全 envelope，partial/legacy 使用分区级降级；
- prompt 详情只返回已持久化且已脱敏的 snapshot，不生成或推断模型私有思维链；
  config 使用允许字段清单，密钥只返回“已配置/未配置”；tool 返回工具名、参数摘要、
  状态与错误分类，永不返回工具或供应商 raw response；tool 参数摘要必须经过密钥、
  token、cookie、路径、locator 和长值 redactor；
- artifact summary 的 `content_exposure` 由服务端 kind allowlist 判定为
  `safe_inline | download_only | prohibited`，未知 kind 默认 `prohibited`；只有 allowlist 中已
  脱敏的 report/public research text 或 JSON 且不超过固定 256 KiB 才能内联；prompt
  与 config 必须走各自 detail kind 的专用 redactor，不能通过 artifact kind 绕过；
- 超阈值或 `download_only` 只返回元数据和当前 run 已验证的既有 artifact read URL；
  `prohibited` 返回 `content_sensitive` 且没有 URL；二进制内容不注入 DOM；
- 本项目当前是 localhost 单用户应用，没有账户级授权层；P2-4 沿用现有本机信任边界，
  并强制 run/item 归属校验。多用户身份、远程部署和可转移下载授权不在本 story
  范围内；若未来引入远程访问，必须先在所有 run/artifact API 上统一增加授权，不能
  把 Audit 的 membership check 当作账户授权。

#### 前端组件与状态

- `useAuditSummary(runId, open)` 只在 `open=true` 时请求摘要，负责取消、成功缓存和
  当前请求重试；
- `useAuditDetail(runId, sourceSequence, selection)` 只在非空 selection 时请求详情，
  按 `(run_id, source_sequence, kind, id)` 缓存成功结果，取消旧请求并阻止旧响应或
  不同 source sequence 的响应覆盖当前 selection；
- `AuditCenter` 管理全屏 modal、入口上下文、当前分区、selection、焦点和关闭恢复；
  `WorkbenchLayout` 只负责打开/关闭并传递可选角色或阶段上下文，不读取审计数据；
- 分区组件只渲染 summary DTO；`AuditDetailPanel` 统一展示详情、下载入口以及加载、
  typed 404、普通错误和重试状态，不直接访问 API；
- 打开状态显式建模为
  `closed → summary-loading → summary-ready/summary-unavailable/summary-error →`
  `browsing → detail-loading/detail-ready/detail-unavailable/detail-error`；summary 的
  partial/legacy 是 `summary-ready` 内的数据可用性，不是网络错误；
  切换分区清空 selection 并取消进行中的详情请求，但保留当前 run 的成功缓存；
- 切换 run 清空摘要、详情、过滤与入口上下文；状态不写 URL 或 localStorage，刷新不
  恢复 Audit Center。

#### 布局、焦点与入口上下文

- Audit Center 是覆盖应用内容的全屏 modal 工作区：顶部运行信息与关闭操作，左侧
  分区导航，中间摘要列表，右侧单项详情；背景 Reader 保持挂载；
- 入口带角色或阶段上下文时只切换到相关分区并高亮摘要项，不自动读取详情；没有
  上下文时默认进入概览；角色上下文映射 roles item，阶段上下文映射 overview 的
  `stage_navigation`；找不到映射时保留目标分区并显示安全提示，不创建 detail selection；
- modal 使用 `role=dialog`、`aria-modal=true` 和稳定标题关联；打开时焦点进入关闭控制
  并约束在 modal 内；关闭后使用 `preventScroll` 返回原触发入口；若入口已卸载，则
  返回当前 Reader 标题；两者都不可用时返回应用主内容容器，不改变 Reader 滚动位置；
- 有详情 selection 时第一次 `Escape` 只清空详情，第二次才关闭工作区；没有详情时
  第一次 `Escape` 直接关闭；
- 视口不小于 1400px 时使用左导航 + 摘要 + 非模态详情三栏，详情更新不抢走摘要入口
  焦点；小于 1400px 时，选择详情打开 Audit modal 内的右侧覆盖层，焦点进入返回/关闭
  详情控制，并将底层导航与摘要设为 inert/`aria-hidden`，焦点只约束在详情层；
  `Escape`、返回控制或关闭详情后焦点回到摘要触发项。分区和摘要列表在详情关闭后
  保持可操作，不增加手机底部 sheet；
- 动画只使用短距离透明度/位移，`prefers-reduced-motion` 下禁用非必要动画。

#### 数据与错误边界

- 初始 Reader 和关闭状态不得发起 Audit 请求；入口上下文只影响打开后的摘要分区，
  不得触发 detail；每次重新打开可以立即显示成功缓存，但必须后台重新验证 summary；
- summary 和 detail 都只缓存成功结果；summary 响应携带 `source_sequence`，关闭后
  可保留最后成功结果以便立即恢复，但每次重新打开都在后台重新验证；工作区顶部另有
  显式刷新操作；每次成功重新验证或刷新都先取消所有进行中 detail 请求，再原子替换
  summary。若 `source_sequence` 改变，则清空该 run 的全部 detail cache，而不只是已
  删除 ID；当前 selection 仍存在于新索引时使用新 sequence 重新读取，否则清空；
  detail 请求的 `v` 过期时服务端返回 typed `audit_summary_stale` 409，前端刷新 summary
  而不展示旧 detail；客户端只接受与 active summary `source_sequence` 完全相等的响应；
  selection 改变或 run 切换取消进行中的对应请求，取消不显示错误；失败重试只作用于
  当前 run 或 selection key；
- run 不存在沿用 `run_not_found` 404；summary unavailable、分区 partial/legacy、
  detail typed 404 和普通网络错误使用不同状态文案；
- Audit Summary 或 Detail 的加载和失败不清空、不重载、不降级 Reader，也不回退
  旧 `AuditReader` 或任意 raw artifact 接口。

#### 验收

- 后端契约覆盖 completed、failed、cancelled/interrupted、partial 与 legacy，以及
  八种 detail selection 的当前 run 归属、跨 run/伪造 ID、脱敏和 typed 404；
- 测试 256 KiB 边界、二进制/不支持媒体类型、下载描述，并证明投影不调用模型或
  外部数据供应商；
- Hook 测试覆盖关闭时零请求、每次打开只发起一次 summary 重新验证、二次选择 detail、
  请求取消、旧响应隔离、成功缓存、显式刷新、失败重试和 run 切换清理；
- 组件测试覆盖所有终态入口、六分区、入口上下文预选、分层 `Escape`、焦点约束、
  关闭后焦点/滚动恢复、partial/legacy 空态和大型内容下载模式；
- Reader 初始响应与 DOM 继续不包含 Audit raw 数据，旧 `AuditReader` 不再挂载；
- Playwright 使用 1512px 检查三栏、长 Prompt/JSON 与关闭恢复，使用 1200px 检查
  工作区内详情覆盖；键盘全流程和 reduced-motion 通过；
- 前端定向 Vitest、typecheck、production build、静态产物同步、后端契约回归与
  `git diff --check` 通过，并记录既有全量测试基线。

实现与验收：终态 `AuditReader` 已由常驻但关闭时零请求的 `AuditCenter` 替换，
Decision Brief、Reader 审计计数、Stage Detail 与失败运行均传递明确入口上下文；
运行中的 `Inspector` 独立保留为“实时审计栏”。服务端新增封闭 DTO、summary/detail
投影和两个只读 API，强制 terminal、同 run membership、source sequence、256 KiB
阈值与 prompt/config/tool/artifact 脱敏策略。审计专项后端 34/34、前端 13/13 通过，
Ruff、typecheck、production build 和静态产物同步通过。Playwright 使用真实历史运行
在 1512×982 验证三栏，在 1280×832 验证内层详情 modal、inert/`aria-hidden`、双层
`Escape` 与入口回焦；最终浏览器控制台 0 error、0 warning。完整套件中的既有失败
继续按 6.1 的基线记录，不归入 P2-4。

### 5.6 P2-5：视觉与 golden QA（5 points，Merged）

**目标：** 在不重做已确认 Reader、Companion 和 Audit Center 交互的前提下，
建立可重复、可提交的桌面视觉基线，并把隐私、键盘和可访问性从人工检查收敛为
可执行回归。P2-5 只允许验收驱动的间距、断行、焦点、对比度和窄屏布局修复，
不改变数据契约或交互语义。

#### 测试架构

- 在 `frontend/` 内建立正式 Playwright 配置和 Reader golden 测试入口，继续使用
  `npm --prefix frontend run test:e2e`；浏览器固定为 Chromium，并固定时区、语言、
  颜色模式、动画和截图参数；
- Playwright 路由拦截返回本地脱敏 fixture，不连接模型、供应商或用户历史数据，
  但页面仍从真实 React 应用启动；
- 11 张批准后的截图基线进入 Git，临时报告、失败截图和 trace 不进入 Git；实现时
  必须同步调整 `.gitignore`，只放行 P2-5 的 Playwright 配置、用例、fixture 和
  snapshot 目录，禁止用 `git add -f` 绕过提交边界；默认测试只比较基线，只有显式
  `--update-snapshots` 才能更新图片；
- 新增 `@axe-core/playwright`，它是 P2-5 唯一新增的 devDependency，用于自动化
  WCAG 规则扫描；键盘、焦点、`Escape` 和回焦使用明确的 Playwright 操作断言；
- production build 继续直接写入 `tradingagents/web/static/`，提交后再次 build 不得
  产生新的静态产物差异。

#### Fixture 与隐私边界

- `typed`：完整 Reader、论点变化、Companion 入口和 Audit 入口均可用；
- `partial`：Reader 可读，但证据覆盖和部分审计分区明确缺失；
- `failed`：运行失败，只展示安全失败摘要、已有阶段信息和审计入口；
- `legacy`：旧运行没有 typed Reader，不伪造新结构，显示明确的 legacy 降级说明；
- 四类 fixture 均使用虚构公司、虚构论点和固定时间，不复制真实历史 run；fixture
  与生产契约共享 TypeScript 类型，使破坏性 DTO 变化在编译期失败；
- 私有延迟接口使用合成敏感哨兵。初始 Reader 响应与 DOM 递归禁止 Prompt、locator、
  hash、完整 CSV、raw 内容和 content-addressed ID；Audit summary/detail 与 Companion
  detail 在主动操作前请求数必须为零，操作后也只能出现相应公开 DTO 允许的内容。

#### Golden 矩阵与视觉边界

- golden 的唯一生成/比较环境为 macOS arm64，使用 `npm ci` 安装 lockfile 中固定的
  Playwright 与 Chromium revision，并使用 macOS 系统字体栈；其他 OS 只运行语义、
  隐私和交互断言，不比较像素基线；
- 所有截图固定 DPR 1、`zh-CN`、`Asia/Shanghai`、light color scheme，并按下表
  固定页面滚动锚点；等待 `document.fonts.ready` 和当前场景所需的 mocked
  请求全部完成后再截图；截图根
  为 `page` 的当前 viewport，不使用 locator screenshot 或 `fullPage`；pixelmatch
  `threshold=0.15`，且
  `maxDiffPixelRatio=0.002`，超过即失败，不允许用放宽容差替代缺陷修复；
- 在应用脚本执行前使用 Playwright Clock 把浏览器时间固定为
  `2026-08-11T08:00:00+08:00`，并断言 Controls 的分析日期为 `2026-08-11`；同时
  关闭动画、隐藏光标并固定 fixture 时间；以下 11 项是唯一基线场景：

| 基线 | 视口 | 截图前状态 | 固定 selection | 滚动 / 根 |
|---|---:|---|---|---|
| typed-wide-companion | 1512×982 | Reader 顶部，Companion pinned | `claim:claim-growth` | Reader 锚点 / page viewport |
| typed-wide-audit | 1440×900 | Audit Center artifacts 分区 + inline detail | `artifact:artifact-report` | 0 / page viewport |
| typed-companion-drawer | 1280×832 | Reader 顶部，Companion drawer | `evidence:evidence-filing` | selection 锚点 / page viewport |
| typed-audit-overlay | 1200×800 | Audit Center tools 分区 + detail overlay | `tool:tool-market` | 0 / page viewport |
| typed-narrow-reader | 768×900 | Reader 顶部，无 overlay | 无 | Reader 锚点 / page viewport |
| partial-reader | 1440×900 | Reader 顶部，无 overlay | 无 | Reader 锚点 / page viewport |
| partial-narrow-audit | 768×900 | Audit Center partial overview | 无 | 0 / page viewport |
| failed-reader | 1440×900 | FailedRunView 顶部 | 无 | 0 / page viewport |
| failed-narrow-audit | 768×900 | FailedRunView 的 Audit overview | 无 | 0 / page viewport |
| legacy-reader | 1440×900 | legacy 降级页顶部 | 无 | Reader 锚点 / page viewport |
| legacy-narrow-audit | 768×900 | legacy Audit overview | 无 | 0 / page viewport |

- 1512/1440 验证宽屏 Companion 和 Audit inline detail，1280/1200 验证抽屉与
  Audit detail overlay，768 验证单列 Reader、中文断行和极窄桌面窗口，不承诺
  手机体验；当前 760/720px 相关规则必须对齐到 768px，并用 768/769px 断言锁定
  单列边界；
- 另用尺寸断言检查横向溢出、列宽、抽屉和 modal 边界；
- 继续复用现有 tokens、卡片、`RoleIcon`、`SafeMarkdown` 和研究终端视觉，不引入
  第二套视觉语言。

#### 可访问性与交互验收

- 以 WCAG 2.2 AA 为目标，但不宣称整站认证；axe 固定启用 `wcag2a`、`wcag2aa`、
  `wcag21aa`、`wcag22aa` tags，对 typed/partial/failed/legacy Reader、Companion
  pinned/drawer、Audit modal 与 inner detail overlay 分别要求零 violation；不得使用
  全局 exclude 或 disable，单节点例外必须先在本文说明理由并由用户确认；
- 覆盖 Tab 顺序、可见焦点、Companion 开关/回焦、Audit Center 焦点约束、分层
  `Escape` 和关闭后回焦；
- 验证 modal/drawer 的 `aria-modal`、`aria-hidden`/`inert` 语义；
- 验证中文、长英文标识和链接不造成横向溢出；
- `prefers-reduced-motion` 下动画和过渡必须关闭。

#### 验收与交付

- 首次生成基线后逐张检查，并向用户集中展示有代表性的宽屏、1200px、768px 和
  异常态结果；测试失败不得被直接解释为需要更新 golden；
- 依次通过 Reader 定向 Vitest、typecheck、production build、11 组 golden、WCAG、
  键盘/焦点/隐私/reduced-motion、Ruff、相关后端契约回归与 `git diff --check`；
- 既有全量测试失败继续作为基线单独记录，不扩大 P2-5 修复范围；
- 规格、命令和最终验收只更新本文；仅当用户入口确有变化时才更新 README，不新增
  进度、验收或 handoff Markdown；
- 设计提交后状态为 `Design Approved`；生产实现、静态产物和全部验收完成后更新为
  `Branch Ready`，且不自动推送远端。

实现与验收：已建立固定时间、视口和脱敏 fixture 的 Playwright/axe 测试架构，
并提交 11 张 macOS arm64 golden。验收驱动的修复仅涉及颜色对比度、
768/769px 单列边界、长标识换行，以及 Companion/Audit 的 inert、分层
`Escape` 和回焦。P2-5 专项 Playwright 21/21、Reader 定向 Vitest 25/25、
相关后端回归 34/34、Ruff 和 typecheck 通过；11 张基线已人工检查，
代表性宽屏、1200px、768px 与异常态结果已由用户确认。

## 6. 开发与验收约定

### 6.1 正确工作目录

Editable install 可能指向另一个 checkout。后端验证必须显式指向当前 worktree：

```bash
PYTHONPATH="$(pwd)" conda run -n tradingagents python -m pytest -q tests
conda run -n tradingagents ruff check tradingagents tests
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- e2e/reader-golden.spec.ts e2e/reader-quality.spec.ts
git diff --check
```

P1-7 现在允许并跟踪唯一的 `tests/test_thesis_diff.py`，覆盖五态、反证守卫、
同时间戳 tuple 基线排序、post-completion provenance/幂等、Reader HTTP 投影
和取消终态方法边界。P2-2 另外跟踪一个 Reader 组件 fixture 及最小 Vitest
配置；其余本地测试资产继续被忽略。

当前验证：P2-5 Playwright 专项 21 passed，包含 11 个 golden 和 10 个
隐私、WCAG 目标、键盘/焦点、响应式与 reduced-motion 断言；Reader 定向
Vitest 25 passed，相关后端契约回归 34 passed；Ruff、前端 typecheck 和 production
build 通过。
完整后端本地套件为 1566 passed、17 failed、68 subtests passed；17 项中 4 项来自
受限环境（1 项 live-network、3 项用户日志目录权限），其余 13 项是 P2-4 前已存在的
legacy 默认行为/旧投影契约断言。完整前端本地套件仍有 2 项既有失败：Controls 的
旧组合约束入口断言与 App 的旧常驻审计栏文案断言；两项测试文件均为本地忽略资产，
不触及 P2-5 目标路径。本地旧 `workbench.spec.ts` 在未启动运行 API 的
Playwright webServer 下仍有 12 项既有失败，与基于确定性路由 fixture 的 P2-5
专项分开记录。不能把完整套件误报为全绿。

### 6.2 Definition of Done

每个 story 必须：

- 有清晰 acceptance criteria；
- 新行为先有失败测试；
- 目标测试和相关回归通过；
- Python 改动通过 Ruff；
- 前端改动通过 typecheck 和 production build；
- 构建后同步受 Git 跟踪的静态产物；
- 更新本文的唯一状态表；
- 不修改旧 artifact，不保存模型私有思维链；
- 不泄漏供应商原始异常、密钥、Prompt、locator 或内容哈希。

真实 LLM 冒烟只在修改 ResearchCase 组装、运行终态或 LLM 结构化输出边界时执行。纯 Reader UI story 使用确定性 fixture，不把网络测试作为完成前提。

### 6.3 提交边界

- `CLAUDE.md` 已由用户明确授权删除，仓库不创建替代 Agent 规则文件；README
  同步移除对该文件的引用，不得保留死链接。
- `tests/` 默认保持本地忽略；`.gitignore` 只显式允许 P1-7 的
  `tests/test_thesis_diff.py`、P2-3a 的 `tests/test_reader_companion.py` 和 P2-4 的
  `tests/test_reader_audit.py`。新增其他测试必须单独评估，不能用 `git add -f`
  临时绕过。
- 前端测试默认保持本地忽略；当前只显式允许 P2-2、P2-3 和 P2-4 的 Reader 请求、
  Hook、组件、隐私与 Workbench 集成回归，以及 Vitest 配置和共享 cleanup setup，
  以保证新 checkout 可直接复现这些 story。
- P2-5 实现必须同步修改 `.gitignore`，只额外放行 `frontend/playwright.config.ts`、
  P2-5 的 `frontend/e2e/` 用例、四类脱敏 fixture 与 snapshot 基线；Playwright
  report、trace、失败截图和 test-results 继续忽略，禁止用 `git add -f` 临时绕过。
- 修改 `frontend/src/` 后必须 rebuild，并检查 `tradingagents/web/static/`。
- 单个 story 超过 8 points 时先拆分；默认同时只推进一个 story。
- 不再创建 dated spec、plan、status、report 或 handoff Markdown。

### 6.4 合入 CI 合同（Merged）

- 仓库删除且不再维护 `CLAUDE.md`；README 移除对它的引用，只保留当前使用和
  产品文档列表，不创建替代 Agent 规则文件；验收时要求 `CLAUDE.md` 不存在且
  README 无死引用；
- GitHub Actions 的 `web-tests` 在干净 checkout 中安装 `.[web,dev]`，运行已跟踪的
  Thesis Diff、Companion 和 Audit 后端契约测试，命令固定为
  `python -m pytest -q tests/test_thesis_diff.py tests/test_reader_companion.py tests/test_reader_audit.py`；
- CI 从仓库根运行 `npm --prefix frontend ci`、`npm --prefix frontend run test -- --run`、
  `npm --prefix frontend run typecheck` 和 `npm --prefix frontend run build`，随后用
  `git diff --exit-code -- tradingagents/web/static/` 检查 production build 漂移；
- Chromium 安装 step 在 `frontend/` 工作目录运行
  `npx playwright install --with-deps chromium`；随后回到仓库根执行
  `npm --prefix frontend run test:e2e -- e2e/reader-golden.spec.ts e2e/reader-quality.spec.ts`；
  Linux 预期 `reader-quality` 10 passed、`reader-golden` 11 skipped，只强制隐私、WCAG 目标、
  键盘/焦点、响应式和 reduced-motion 语义断言；11 张像素基线仍只在 macOS
  arm64 生成和比较；
- 现有 Ruff、安装/导入、wheel 静态产物和 CLI smoke 门禁保留；远端结果必须等
  推送或 PR 的当前执行结果仍须在对应远端运行中单独确认，不能由本文的
  历史验收记录替代。

实现与验收：`web-tests` 已安装 `.[web,dev]` 并接入精选后端契约、全部已跟踪
Vitest 和 Reader Playwright specs；过时的 local-only 测试注释已删除。本地等价门禁为
后端 34 passed、Vitest 25 passed、macOS Playwright 21 passed，Ruff、CI YAML 解析、
typecheck、production build 及静态产物幂等均通过。Ubuntu 上的 10 passed / 11 skipped
只能在分支推送后由 GitHub Actions 最终确认。

## 7. 关键代码入口

| 关注点 | 入口 |
|---|---|
| 请求、兼容与公开错误 | `tradingagents/web/schemas.py`, `tradingagents/web/api.py` |
| 运行模型与恢复 | `tradingagents/execution/models.py`, `tradingagents/runtime/run_models.py` |
| 周期与覆盖策略 | `tradingagents/research/horizon_policy.py`, `tradingagents/dataflows/coverage.py` |
| 复权价格能力 | `tradingagents/research/price_coverage.py` |
| Research Case schema | `tradingagents/agents/schemas/_research_case.py` |
| Claims 与 assembler | `tradingagents/agents/managers/research_manager.py` |
| 资格与数据质量 | `tradingagents/research/eligibility.py` |
| 公共产物提交 | `tradingagents/execution/output_publisher.py` |
| Thesis Diff | `tradingagents/research/thesis_diff.py` |
| Run 成功终态 | `tradingagents/web/manager.py` |
| Reader DTO 与投影 | `tradingagents/web/reader_models.py`, `tradingagents/web/reader_projection.py` |
| Reader API | `tradingagents/web/api.py` |
| 前端 Reader | `frontend/src/components/reader/ReaderSurface.tsx` |
| 前端 Reader 请求 | `frontend/src/hooks/useReader.ts`, `frontend/src/api/contracts.ts` |
| Audit DTO 与投影 | `tradingagents/web/audit_models.py`, `tradingagents/web/audit_projection.py` |
| 前端 Audit Center | `frontend/src/components/reader/AuditCenter.tsx`, `frontend/src/hooks/useAudit.ts` |
| P2-5 Reader QA | `frontend/playwright.config.ts`, `frontend/e2e/reader-*.spec.ts` |

## 8. 维护规则

- 本文只描述当前有效状态，不追加日期型开发日志。
- 改变本文范围内的现役行为时，在同一 commit 或 PR 中更新状态表。
- 详细实现历史通过 commit、PR 和 blame 查询。
- 临时交接文档可以存在于个人工作区，但不能成为仓库事实来源。
- 废弃设计由 Git 历史保留，不额外建立 archive 文档。
