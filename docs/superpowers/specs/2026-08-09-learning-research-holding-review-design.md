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

新增独立 `HoldingContext`，不把最小持仓伪装成完整 Portfolio：

```text
HoldingContext
  ticker: str
  quantity: finite number > 0
  average_cost: finite number > 0
  sellable_quantity: finite number >= 0 | null
  cash: finite number >= 0 | null
  total_account_value: finite number > 0 | null
```

约束：

- `sellable_quantity` 不得超过 `quantity`。
- 不使用交易所整手规则限制 `quantity`；这是复盘输入，不是订单输入。
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
- `holding_review` 只注入用户明确提供的 `HoldingContext`。
- 用户输入的数量、成本、现金与总资产必须保留“用户提供事实”的来源语义。
- 行情、公司与行业事实继续来自确定性数据能力，不以用户成本价替代市场价格。
- mode、horizon 或 holding facts 变化均改变 fingerprint，不得复用旧 checkpoint。
- retry/resume/snapshot/SSE 对同一运行必须报告同一个 mode 与 horizon。

## 4. 输出语义

### 4.1 公司研究

`company_research` 重点输出：

- 研究评级与置信度；
- 事实、推论和未知；
- 三情景；
- 催化剂、失效条件与复核计划；
- 数据质量与审计入口。

该模式不得产生：

- 推荐持仓比例；
- 买卖股数；
- 订单、价格指令或执行时间；
- 伪造的账户约束。

### 4.2 持仓复盘

`holding_review` 在公司研究基础上增加：

- 原始持仓逻辑是否仍成立；
- 成本基础与当前研究情景的敏感性；
- 集中度是否可计算；
- 主要风险暴露与失效条件；
- 下一次复核所需证据。

没有 `total_account_value` 时：

- 组合占比 unavailable；
- 推荐仓位 unavailable；
- 交易股数 unavailable；
- 不允许模型估算 NAV 或完整账户。

允许输出“增加关注、维持观察、降低风险暴露”等研究语言，但必须明确它是复盘意见，不是交易指令。Portfolio Manager 在此模式中承担持仓风险复盘职责，不承担订单生成或执行职责。

## 5. 前端交互

表单默认选择“公司研究”。选择“持仓复盘”后才展示：

- 持仓数量；
- 平均成本；
- 可卖数量（可选）；
- 现金（可选）；
- 账户总资产（可选）。

固定提示：

> 用于学习和复盘现有或模拟持仓，不构成交易指令，也不会连接券商或执行订单。

前端请求规则：

- 公司研究不发送 `holding`。
- 持仓复盘不发送未填写的可选数字。
- 切换回公司研究时清除持仓字段的请求语义，避免隐藏字段泄漏到新运行。

## 6. 兼容策略

旧请求或快照缺少 `mode` 时：

- 存在 legacy `portfolio` → 归一化为 `holding_review`；
- 不存在 legacy `portfolio` → 归一化为 `company_research`。

旧请求缺少 `horizon` 时继续使用 `medium`。

Legacy portfolio 可以继续进入现有兼容路径，但不得因此要求新 UI 收集完整账户，也不得把 legacy execution-oriented 字段提升为新版 Reader 的交易语义。

## 7. 校验与公开错误

HTTP 边界保持 `extra="forbid"`。非法组合返回 typed 422，并指向稳定字段路径：

- `holding_review` 缺少 `holding`；
- `company_research` 携带 `holding`；
- quantity/cost/cash/NAV 非有限或超出范围；
- sellable quantity 超过 quantity；
- holding ticker 与 run ticker 不一致。

系统不得静默忽略不适用于当前模式的字段。

## 8. 验证标准

### 8.1 后端

- 新请求默认 company research + medium。
- holding review 只要求 ticker、quantity、average cost。
- company mode 拒绝 holding；holding mode 缺 holding 时拒绝。
- 缺少 NAV 的 holding review 可以运行，但占比与交易数量保持 unavailable。
- snapshot、retry、resume、fingerprint、SSE 与 AgentState 保持 mode/horizon/holding 一致。
- legacy portfolio 正确推断 holding review；无 portfolio 的 legacy 快照推断 company research。

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
- 缺少 NAV 时的推荐仓位或交易股数。
