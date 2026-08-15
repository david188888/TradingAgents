# Wind AIFin Market 集成（当前能力）

- **Status: Current**
- 本文只描述当前代码中**真正支持**的 Wind 能力、配置、路由和限制；它是 current-state 操作文档，不作为未来扩展的规划。
- 历史调研、架构决策与分阶段实施方案见 [docs/archive/plans/2026-08-12-wind-a-share-integration-plan.md](../archive/plans/2026-08-12-wind-a-share-integration-plan.md)。

## 概览

Wind AIFin Market 通过官方 `wind-mcp-skill` CLI（固定版本 `2.0.1`）接入。生产数据只来自固定的 7 个 MCP server 中的 `stock_data`、`index_data`、`economic_data` 三个族，并遵守以下设计规则：

- 一次只有一个 Wind 请求在途（Wind 默认串行；bundle 级并行不得传导到 Wind）。
- `null` / `INVALID` 表示缺失，永远不当作 0。
- `analytics_data` 不会被自动选择为任何主备链的一部分。
- 符号转换只把已明确的上海市场内部代码 `.SS` 转成 `.SH`；裸 6 位代码一律拒绝猜测交易所。

## 已实现能力

| 规范化能力 | Wind 工具 | 说明 |
|---|---|---|
| 复权行情 | `stock_data.get_stock_kline` | A 股日线、前复权（`period=1d`、`aftype=0`、`issusp=0`），显式记录 `price_basis=qfq`、实际日期窗口与 provenance |
| 指数快照 | `index_data.get_index_quote` | 注册表内指数的最新快照 |
| 指数历史 | `index_data.get_index_kline` | 注册表内指数日线历史 |
| 指数档案 | `index_data.get_index_basicinfo` | 指数基本信息 |
| 指数基本面/估值 | `index_data.get_index_fundamentals` | PE/PB/股息率等估值字段 |
| 宏观/行业 EDB 搜索 | `economic_data.natural_language_get_edb_data`（search） | 自然语言搜索返回候选指标（code/name/freq/unit） |
| EDB 时序取数 | `economic_data.natural_language_get_edb_data`（fetch） | 用审核后的 EDB code 拉取时序 |
| 股票风险指标 | `stock_data.get_risk_metrics` | Beta、年化波动率、最大回撤、夏普比率等 |

### 指数注册表

只有显式注册的指数才允许进入 Wind 指数路径，裸 `000xxx` 代码（可能是 `000001` 平安银行）不会猜测：

`000300.SH`（沪深300）、`000905.SH`（中证500）、`000852.SH`（中证1000）、`000016.SH`（上证50）、`000010.SH`（上证180）、`000688.SH`（科创50）、`000001.SH`（上证指数）、`399001.SZ`（深证成指）、`399006.SZ`（创业板指）、`399303.SZ`（国证2000）。

### EDB allowlist

生产取数使用审核后的 EDB code。当前 allowlist 仅含两个 GDP 序列（`M0001395` 中国 GDP 现价年度、`M5567876` 中国 GDP 现价当季值）；`wind_strict_edb_allowlist: true` 时，allowlist 外的 code 会被拒绝，不传递给 Wind。搜索返回的候选 code 需要人工审核后使用。

## 配置与路由

| 配置项 | 默认值 | 含义 |
|---|---|---|
| `wind_enabled` | `true` | 是否启用 Wind 能力（关闭不影响核心研究路径） |
| `wind_max_concurrency` | `1` | Wind 并发上限（保持串行） |
| `wind_request_timeout_seconds` | `120` | 请求硬超时 |
| `wind_strict_edb_allowlist` | `false` | 是否强制 EDB allowlist |
| `wind_pinned_skill_version` | `2.0.1` | 固定 skill 版本 |
| `WIND_API_KEY` | — | 认证密钥（通过环境变量注入） |
| `WIND_CLI_PATH` | `~/.claude/skills/wind-mcp-skill/scripts/cli.mjs` | CLI 路径（解析符号链接） |

注册在 `tradingagents/dataflows/registry.py` 与 `tradingagents/default_config.py` 的默认链：

- `get_adjusted_price_history`：`wind, tushare, akshare, yfinance, alpha_vantage`（Wind 第一）
- `wind_index_data`：`wind, eastmoney`（指数快照/历史在 Wind 不可用时降级到 EastMoney keyless 公开接口；指数档案/基本面无公共 fallback）
- `wind_macro_data`：`wind`
- `wind_risk_data`：`wind`

A 股补充能力（资金流、两融、公告、大宗、龙虎榜、涨停梯队、互动易、iWenCai 等）走各自独立来源，不经过 Wind。

## 未实现范围（截至本文核验日期）

以下能力**尚未**接入生产链，不能当作已交付功能：

- Wind 财务报表/公司基本面（`stock_data.get_stock_fundamentals`）：A 股三大报表仍走 `tushare → sina → yfinance → alpha_vantage`。
- Wind 公司新闻/事件（`financial_docs.get_financial_news`、`stock_data.get_stock_events`）：新闻仍走 `tavily → eastmoney → yfinance → alpha_vantage` 降级链。
- Wind 公告语义检索（`financial_docs.get_company_announcements`）：官方公告仍以 CNINFO/交易所原站优先。
- `fund_data` / `bond_data` / `analytics_data`：不进入当前默认路由。

## 错误与降级语义

- `AUTH_ERROR`、`DAILY_LIMIT_ERROR`、`BALANCE_ERROR`：标记人工恢复/额度周期锁定，不做短时自动重试；多供应商链可降级，Wind-only 能力应失败。
- `RATE_LIMIT_ERROR`、`NETWORK_ERROR`、`TEMPORARILY_UNAVAILABLE`：transport 有界重试后按链降级。
- `NO_RESULTS`：只允许受控缩窄/改写，不解释为“事件不存在”。
- `MARKET_TARGET_NOT_FOUND`：要求准确名称或 Wind code，不猜后缀。
- 带数据的 warning 保留数据并标记 `partial`。
- CLI 未安装、未配置 key、`wind_enabled=false` 时，Wind 相关能力返回类型化不可用（`VendorNotConfiguredError` / 对应降级），不影响其他 A 股主路径。

## 代码入口

- Provider / transport：`tradingagents/dataflows/wind_provider.py`
- Agent 工具包装：`tradingagents/agents/utils/wind_data_tools.py`
- 注册与路由：`tradingagents/dataflows/registry.py`、`tradingagents/default_config.py`
- 本地 index fallback：`tradingagents/dataflows/index_provider.py`
- 测试：`tests/test_wind_provider.py`、`tests/test_index_and_risk_metrics_local.py`、`tests/test_index_provider_route_compat.py`
