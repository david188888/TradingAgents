# TradingAgents 学习型公司研究与持仓复盘设计

**状态：** 待实现  
**日期：** 2026-08-09  
**范围：** Phase 1 / P1-1 双模式与三周期输入增量  
**依赖：** `2026-08-09-tradingagents-decision-reader-design.md`

## 1. 产品边界

TradingAgents 保持原有定位：它是股票与公司研究分析工具，不是交易系统。
系统不连接券商、不生成订单、不执行交易，也不把研究输出描述为个性化交易指令。

首版提供两个显式研究模式：

- `company_research`：默认模式，用于理解公司、股票、行业、风险和研究论点。
- `holding_review`：用于学习和复盘现有或模拟持仓，重点检查持仓逻辑、风险、盈亏敏感性、失效条件与复核计划。

持仓复盘不要求完整账户或大额资金。用户只需提供目标标的的持仓数量和平均成本；现金与账户总资产均为可选事实。

### 1.1 规范覆盖关系

本文件是依赖设计中 P1-1、P1-6 与 Phase 2 输入/展示条款的产品语义增量。发生冲突时以本文件为准：

- `holding_review` 取代此前的 `position_decision` 命名与语义。
- 新请求不要求完整 Portfolio 或 NAV。
- `HoldingContext` 取代新版 UI 的 Portfolio 输入。
- 两种模式都不生成推荐仓位、目标仓位、买卖股数或订单参数。
- 未冲突的 Reader、证据、审计、数据质量与 Companion 契约继续沿用依赖规范。

## 2. 公开输入契约

### 2.1 模式与周期

```text
mode:
  company_research
  holding_review

horizon:
  short
  medium
  long
```

新请求默认：

- `mode = company_research`
- `horizon = medium`

### 2.2 最小持仓事实

公开请求使用 `HoldingInput`；归一化后形成 `HoldingContext`，不把最小持仓伪装成完整 Portfolio：

```text
HoldingInput
  ticker: str
  quantity: finite number > 0
  average_cost: finite number > 0
  cash: finite number >= 0 | null
  total_account_value: finite number > 0 | null
  currency: ISO-4217 string | null
  facts_as_of: YYYY-MM-DD | null
  original_thesis: string | null

HoldingContext
  <all normalized HoldingInput fields; omitted optionals become null>
  source: user_provided | legacy_portfolio
```

约束：

- 不使用交易所整手规则限制 `quantity`；这是复盘输入，不是订单输入。
- `average_cost` 是每单位账面成本，不是总成本，也不是当前市场价格。
- `total_account_value` 是用户提供的账户总权益事实，包含现金与持仓；不得从 `cash` 反推。
- 首版不做自动换汇或混合币种计算。`currency` 未提供时保留为 null，并始终视为 `currency_unverified`；instrument identity 只能证明证券报价币种，不能证明用户金额币种。UI 可以提示常见报价币种，但不得静默替用户选择。
- `facts_as_of` 表示 quantity、average cost、cash 与 NAV 的用户事实时点。省略时在 normalization 中明确填入本次 `analysis_date`；显式提供时必须与 `analysis_date` 相同，否则拒绝。UI 固定提示“持仓事实以分析日期为准”。
- `original_thesis` 是可选的用户原始持仓理由；未提供时不得猜测买入逻辑。
- `company_research` 不得携带新 `holding` 字段。
- `holding_review` 必须携带 `holding`，且 `holding.ticker` 必须与目标 ticker 归一化后相同。
- 未提供 `cash` 或 `total_account_value` 时，不补造账户事实。

现有 `PortfolioRequest` 和 `PortfolioContext` 暂时保留为 legacy 输入边界，供旧请求和旧快照恢复；新 UI 不再以完整 Portfolio 作为持仓复盘的必填模型。

## 3. 运行时数据流

`mode`、`horizon` 和公开持仓事实必须沿同一 wire contract 贯穿：

```text
Controls
  → RunCreateRequest
  → compatibility normalization
  → AnalysisRequest
  → RunSnapshot
  → resume fingerprint
  → run.started SSE
  → AgentState
  → Research Case / Reader
```

规则：

- `company_research` 不向 AgentState 注入 holding/portfolio context。
- `holding_review` 只注入归一化 `HoldingContext`。
- 新输入标记 `source=user_provided`；兼容映射标记 `source=legacy_portfolio`。
- 行情、公司与行业事实继续来自确定性数据能力，不以用户成本价替代市场价格。
- mode、horizon 或 holding facts 变化均改变 fingerprint，不得复用旧 checkpoint。
- retry/resume/snapshot/SSE 对同一运行必须报告同一个 mode 与 horizon。

### 3.1 冻结 wire contract

| 层 | 字段 |
|---|---|
| `RunCreateRequest` | `mode`, `horizon`, `holding`, legacy-only `portfolio` |
| `AnalysisRequest` | `mode`, `horizon`, `holding_context` |
| `RunSnapshot` | `mode`, `horizon`, `holding_context` |
| `run.started` | `mode`, `horizon`, `holding_summary` |
| `AgentState` | `mode`, `horizon`, `holding_context` |

具体语义：

- 新 snapshot 必须显式保存 mode、horizon 和 `holding_context`（公司研究为 null）；字段可缺失只用于 legacy 反序列化。
- company research 的 AgentState 中 `holding_context=null`，且 `portfolio_context=null`。
- omitted 的 HoldingInput 可选值在 normalization 后统一为 null；omitted 与显式 null 产生相同 fingerprint。
- fingerprint 使用归一化 ticker、mode、horizon 和完整的归一化 HoldingContext；任一字段变化都不兼容。
- retry 原样复制归一化上下文。编辑 mode、horizon 或 holding 必须创建新运行。
- legacy snapshot 必须先归一化，再计算 resume fingerprint；无法归一化时阻止 resume，不静默转为公司研究。
- `run.started.holding_summary` 在公司研究为 null；持仓复盘只公开 ticker、quantity、average_cost、currency、facts_as_of、source 以及 `has_cash`、`has_total_account_value`、`has_original_thesis`，不在事件流重复现金、NAV 或 thesis 正文。

## 4. 输出语义

### 4.1 公司研究

`company_research` 重点输出：

- 研究倾向与置信度；研究倾向固定为 `favorable | neutral | cautious | insufficient_evidence`，不得使用 BUY/HOLD/SELL 或 `FINAL TRANSACTION PROPOSAL`；
- 事实、推论和未知；
- 三情景；
- 催化剂、失效条件与复核计划；
- 数据质量与审计入口。

两种模式都不得产生：

- 推荐或目标持仓比例；
- 买卖股数；
- 订单、价格指令或执行时间；
- 伪造的账户约束。

### 4.2 持仓复盘

`holding_review` 在公司研究基础上增加：

- 若用户提供 `original_thesis`，检查其是否仍被当前证据支持；未提供时明确 `original_thesis_not_provided`，只建立可观察的当前研究假设；
- 成本基础与当前研究情景的敏感性；
- 集中度是否可计算；
- 主要风险暴露与失效条件；
- 下一次复核所需证据。

NAV 无论是否存在，都不能解锁推荐仓位、目标仓位、交易股数或订单参数。NAV 只允许用于描述性计算当前持仓市值、当前集中度和情景敏感性。

当前集中度只在以下条件全部满足时计算：用户提供 `total_account_value`、`facts_as_of` 与 analysis date 一致、存在 analysis-date 对齐的可信市场价格、用户显式提供的金额币种与报价币种一致。否则输出结构化 unavailable：

- `total_account_value_not_provided`
- `verified_market_price_unavailable`
- `currency_unverified`
- `currency_mismatch`
- `holding_facts_as_of_mismatch`

盈亏与情景敏感性同样要求可信市场价格、已验证且一致的币种，以及与 analysis date 一致的 `facts_as_of`；不得用平均成本冒充当前价格。

允许输出“增加关注、维持观察、降低风险暴露”等研究语言，但必须明确它是复盘意见，不是交易指令。Portfolio Manager 在此模式中承担持仓风险复盘职责，不承担订单生成或执行职责。

## 5. 前端交互

表单默认选择“公司研究”。选择“持仓复盘”后才展示：

- 持仓数量；
- 平均成本；
- 现金（可选）；
- 账户总资产（可选）。
- 币种（可选）；
- 持仓事实日期（可选，默认本次分析日期）；
- 原始持仓理由（可选）。

固定提示：

> 用于学习和复盘现有或模拟持仓，不构成交易指令，也不会连接券商或执行订单。

前端请求规则：

- 公司研究不发送 `holding`。
- 持仓复盘不发送未填写的可选数字。
- 切换回公司研究时清除持仓字段的请求语义，避免隐藏字段泄漏到新运行。

## 6. 兼容策略

归一化优先级是确定的：

1. `holding` 与 legacy `portfolio` 同时存在：拒绝，不能静默选择。
2. 显式 `company_research` 携带 holding 或 portfolio：拒绝。
3. 显式 `holding_review` + holding：按新契约归一化。
4. 显式 `holding_review` + 仅 legacy portfolio：执行 legacy 映射。
5. mode 缺失 + holding：推断 `holding_review`。
6. mode 缺失 + 仅 legacy portfolio：推断 `holding_review` 并执行 legacy 映射。
7. mode、holding、portfolio 均缺失：推断 `company_research`。

Legacy 映射必须在 portfolio 中找到唯一一个归一化 ticker 与运行目标一致、quantity > 0、average_cost > 0 的仓位。映射 quantity、average_cost、cash 与 portfolio currency；`facts_as_of` 归一化为 analysis date；`total_account_value` 和 `original_thesis` 为 null，不从 mark prices 或 cash 推算。目标缺失、重复或字段无效时分别返回稳定兼容错误；不得回退为公司研究。

旧请求缺少 `horizon` 时继续使用 `medium`。

Legacy portfolio 可以继续进入兼容路径，但其 limits、sellable quantity 与 mark-price execution 字段不进入新版 HoldingContext，也不得提升为 Reader 的交易语义。旧快照无法完成上述映射时，resume 返回 `legacy_resume_normalization_failed` 并要求新建运行。

## 7. 校验与公开错误

HTTP 边界保持 `extra="forbid"`。非法组合返回 typed 422，并冻结 code/path：

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
| `holding_as_of_mismatch` | `holding.facts_as_of` |
| `legacy_target_position_missing` | `portfolio.positions` |
| `legacy_target_position_ambiguous` | `portfolio.positions` |
| `legacy_target_position_invalid` | `portfolio.positions` |

Reader 中不可计算项使用 `{status: "unavailable", reason_code: <stable code>}`，不能只输出自然语言 unavailable。

系统不得静默忽略不适用于当前模式的字段。

## 8. 验证标准

### 8.1 后端

- 新请求默认 company research + medium。
- holding review 只要求 ticker、quantity、average cost。
- company mode 拒绝 holding；holding mode 缺 holding 时拒绝。
- 缺少 NAV 的 holding review 可以运行；有无 NAV 都不得生成推荐仓位或交易数量。
- snapshot、retry、resume、fingerprint、SSE 与 AgentState 保持 mode/horizon/holding 一致。
- legacy portfolio 正确推断 holding review；无 portfolio 的 legacy 快照推断 company research。
- mode × holding × legacy portfolio 的所有组合均有表驱动测试。
- legacy 目标缺失、重复或成本无效时稳定失败，不静默降级。
- omitted/null 的 fingerprint 等价；holding 任一归一化事实变化都会使 fingerprint 不兼容。
- create → snapshot → SSE → resume → AgentState 使用 golden contract 验证。
- company mode 的 AgentState 明确没有 holding/portfolio context。
- 缺 NAV、缺市场价格、币种未验证、币种冲突和持仓事实日期不一致分别产生稳定 reason code。
- legacy 无效目标仓位返回 `legacy_target_position_invalid`；旧快照无法归一化时 resume 返回 `legacy_resume_normalization_failed`。
- 缺 original thesis 时不得推断用户买入理由。

### 8.2 前端

- 默认只显示公司研究字段。
- 切换持仓复盘后显示最小持仓字段和学习提示。
- 公司研究请求不包含 holding。
- 非法最小持仓在本地阻止提交，并与后端字段错误一致。

### 8.3 非目标

本变更不实现：

- 券商连接、订单生成或自动交易；
- 实盘执行确认；
- 完整资产配置或税务建议；
- 模型推测用户风险承受能力；
- 任何模式下的推荐仓位、目标仓位、买卖股数或订单参数。
