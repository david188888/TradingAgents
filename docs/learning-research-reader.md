# TradingAgents 学习型研究与 Reader

**状态：** 持续维护  
**最近核验：** 2026-08-11  
**适用范围：** 学习型公司研究、持仓复盘、Research Case、Thesis Diff、Reader、Companion 与 Audit Center

本文是上述范围的唯一长期事实来源。它记录当前有效的产品边界、系统流程、稳定契约、真实实现状态和剩余路线，不记录逐日开发日志。历史方案、废弃设计和完成过程通过 Git 历史查看。

如果本文与代码不一致，以已经合入 `main` 且通过测试的代码为准，并在同一修复中更新本文。分支上的功能只能标记为 `Branch Ready`，不能提前标记为 `Merged`。

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
  → on-demand Companion / Audit Center (planned)
```

### 2.1 数据层

周期策略、数据窗口、分页预算、复权要求和 required/optional 能力由版本化代码确定，不由 LLM 临时决定。

每个数据能力区分：

- 请求范围与实际观测范围；
- `complete / partial / unknown / unavailable`；
- 页数、是否耗尽和预算截断；
- as-of、降级原因与来源身份。

中长期技术结论要求明确的复权序列。复权数据不可用时，不得用 raw price 推断趋势。历史分析不得混入分析日之后的新闻、公告或当前快照。

### 2.2 研究层

分析师只消费已提交的数据包。Research Manager 输出使用短稳定 claim key 的结构化草稿；assembler 将其解析为当前运行中的 evidence/coverage 引用，并确定性计算 source dates、资格和数据质量。

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

Companion 尚未实现。后续契约只允许 `role / claim / evidence / risk` 四类公开 selection，并校验选择属于当前 run。未知、跨 run 或不可公开 ID 返回 typed 404；前端不得回退到 raw artifact。

Audit Center 尚未独立完成。它必须在用户主动进入后才加载角色、能力、工具和 artifact 摘要；单项 raw 内容还需要第二次显式选择。大型内容只返回元数据和下载入口。

当前 Reader Core 有两条已知的 content-addressed ID 暴露路径：

- `audit_entry.audit_refs`；
- `thesis_diff.current_research_case_artifact_id` 与
  `previous_research_case_artifact_id`。

这些 artifact ID 使用 `kind:sha256` 形式。它们必须在 Companion API 实现前
从默认 Reader DTO 中移除或替换为非内容寻址的 public ID；默认 Reader 只应
保留审计计数和安全入口。验收必须递归检查序列化 Reader 与初始 DOM，禁止
content-addressed ID、locator、hash 和 raw content，而不只检查顶层字段名。

## 4. 当前实现状态

状态只使用：

- `Merged`：已经进入 `main`；
- `Branch Ready`：已完成并推送，但尚未合并；
- `Planned`：尚未完成。

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
| ThesisDiffV1、发布幂等、provenance 与可复现测试 | Branch Ready | `2f818bf` + `codex/reader-roadmap-docs` |
| P2-2 学习报告与论点变化 | Planned | 依赖 ThesisDiff 合入 |
| P2-3a Companion DTO/API 与 Reader 隐私收口 | Planned | Reader Core 后续契约 |
| P2-3b 自适应伴读栏 | Planned | 依赖 P2-3a |
| P2-4 独立 Audit Center | Planned | 依赖安全审计入口 |
| P2-5 视觉、响应式、可访问性与 golden QA | Planned | 依赖 P2-2～P2-4 |

已验证的 typed run：`run_20260810T152235678110Z_aa9f06e0`。它包含 6 个 claims、4 个 analyst cards、partial availability 和 `eligibility=none`，可用于本地 Reader 验收；不得将其私有原始内容提交为 fixture。

## 5. 剩余路线

### 5.1 P1-7 合入前硬化与文档整合（Branch Ready）

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
- `CLAUDE.md` 不进入提交；
- 后端全量测试、Ruff、前端 typecheck/build 和 `git diff --check` 通过。

### 5.2 P2-2：学习报告与论点变化（5 points）

**As a** 重复研究同一公司的读者  
**I want** 在研究正文中看到本轮论点相对上一基线的变化  
**So that** 我能区分新信息、持续假设、反证和未复核内容。

验收：

- 前端契约不再把 `thesis_diff` 固定为 null；
- 五种 diff kind 使用独立中文标签和图标，不只依赖颜色；
- `unresolved` 与 `not_reassessed` 文案不同；
- change flags 分别表达文本、证据、置信度和状态变化；
- counter-evidence 只走安全 public ref，不显示 locator/hash/raw；
- fixture 覆盖有基线、无基线和 diff 不可用。

### 5.3 P2-3a：Companion 公共契约与 API（3 points）

**As a** Reader 用户  
**I want** 按需查看选中论点、角色、证据或风险的伴读摘要  
**So that** 我无需打开 raw 审计数据也能继续理解结论。

验收：

- 新增封闭 `CompanionSelection` 与 `CompanionDTO`；
- selection 只接受 role/claim/evidence/risk；
- 所有公开 ID 都验证当前 run 归属；
- typed 404 不回退 raw；
- DTO 只包含摘要、实际覆盖、结论影响和下一验证；
- Reader 默认响应移除 audit refs 和 ThesisDiff 中的 Research Case artifact IDs；
- 对序列化 Reader 和初始 DOM 做递归隐私断言；
- 跨 run、未知 ID、不可公开 ID 和正常选择有契约测试。

### 5.4 P2-3b：自适应伴读栏（5 points）

验收：

- `useCompanion` 按 `(run_id, kind, id)` 缓存并取消过时请求；
- role/claim/evidence/risk 共用 selection；
- 临时打开、固定和关闭不丢失正文滚动位置；
- 1400px 以下使用覆盖式 drawer，正文不足 720px 时禁止固定；
- 键盘、焦点管理和 reduced-motion 正常；
- 初始 Reader 不预取 Companion 或 raw 数据。

### 5.5 P2-4：独立 Audit Center（5 points）

验收：

- 运行、角色、能力、工具、artifact、prompt/config 分区；
- Reader 到 Audit Center 不超过两步；
- 打开 Audit Center 后才加载摘要；
- 用户选择单项后才加载 raw；
- 超阈值内容只显示元数据和下载入口；
- legacy run 保留完整阶段导航；
- Audit 失败不清空或降级 Reader 正文。

### 5.6 P2-5：视觉与 golden QA（5 points）

验收：

- 复用现有 tokens、卡片、RoleIcon、SafeMarkdown 和研究终端视觉；
- typed、partial、failed、legacy 四类脱敏 fixture；
- 1440、1200、768、390px 视觉回归；
- 键盘、ARIA、焦点、对比度、中文断行和 reduced-motion；
- 初始 Reader 响应及 DOM 不含 Prompt、locator、hash、完整 CSV/raw；
- 前端源码与 `tradingagents/web/static/` 构建产物一致。

## 6. 开发与验收约定

### 6.1 正确工作目录

Editable install 可能指向另一个 checkout。后端验证必须显式指向当前 worktree：

```bash
PYTHONPATH="$(pwd)" conda run -n tradingagents python -m pytest -q tests
conda run -n tradingagents ruff check tradingagents tests
npm --prefix frontend run typecheck
npm --prefix frontend run build
git diff --check
```

P1-7 现在允许并跟踪唯一的 `tests/test_thesis_diff.py`，覆盖五态、反证守卫、
同时间戳 tuple 基线排序、post-completion provenance/幂等、Reader HTTP 投影
和取消终态方法边界。其余本地测试资产继续被忽略。

当前验证：P1-7 + RunManager 生命周期 20 passed；Ruff、前端 typecheck 与
production build 通过。完整本地套件为 1536 passed、17 failed、68 subtests
passed；17 项中 4 项来自受限环境（1 项 live-network、3 项用户日志目录权限），
其余 13 项是本轮改动前已存在的 legacy 默认行为/旧投影契约断言。它们不触及
P1-7 的改动文件，继续作为独立基线债务处理，不能误报为本轮全绿。

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

- `CLAUDE.md` 存在用户本地修改，不得纳入本任务提交。
- `tests/` 默认保持本地忽略；`.gitignore` 只显式允许 P1-7 的
  `tests/test_thesis_diff.py`。新增其他测试必须单独评估，不能用 `git add -f`
  临时绕过。
- 修改 `frontend/src/` 后必须 rebuild，并检查 `tradingagents/web/static/`。
- 单个 story 超过 8 points 时先拆分；默认同时只推进一个 story。
- 不再创建 dated spec、plan、status、report 或 handoff Markdown。

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

## 8. 维护规则

- 本文只描述当前有效状态，不追加日期型开发日志。
- 完成 story 时，在相同 commit 或 PR 中更新状态表。
- 详细实现历史通过 commit、PR 和 blame 查询。
- 临时交接文档可以存在于个人工作区，但不能成为仓库事实来源。
- 废弃设计由 Git 历史保留，不额外建立 archive 文档。
