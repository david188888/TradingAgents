# A 股补充数据能力

- **Status: Current**（current-state 文档；provider 路由变化时对照 `tradingagents/dataflows/registry.py` 与 `tradingagents/default_config.py` 校验）

这些接口是研究补充，而不是行情或基本面的替代。每个结果都会标明实际来源；空结果、SDK 缺失、字段变化、限流或未配置的供应商都会返回类型化的不可用状态，不能被解释为“没有事件”。

| 能力 | 路由方法 | 当前来源 | 输入范围 |
|---|---|---|---|
| 资金流、两融 | `get_a_share_capital_flow`、`get_a_share_margin_financing` | EastMoney 公共接口 | 单只 A 股 |
| 官方披露 | `get_a_share_cninfo_announcements` | 巨潮资讯或上交所/深交所，required any-of | 单只 A 股、周期确定的日期区间 |
| 公告兼容查询 | `get_a_share_exchange_announcements` | 上交所/深交所优先，EastMoney 公开备胎 | 单只 A 股；EastMoney 不计作官方覆盖 |
| 大宗交易 | `get_a_share_bulk_trades` | EastMoney direct（datacenter） | 单只 A 股、日期区间 |
| 股东户数 | `get_a_share_shareholder_counts` | EastMoney direct（datacenter） | 单只 A 股 |
| 限售解禁 | `get_a_share_lockup_releases` | EastMoney direct（datacenter） | 单只 A 股、日期区间 |
| 龙虎榜 | `get_a_share_dragon_tiger` | EastMoney direct（datacenter），交易所官方备份 | 单只 A 股、交易日、买入或卖出 |
| 涨停梯队 | `get_a_share_limit_up_ladder` | EastMoney direct（push2ex） | 交易日；输出当日连板/题材字段计数和成分行 |
| 互动易 | `get_a_share_interactive_questions`、`get_a_share_interactive_answers` | AKShare/CNINFO | 单只 A 股；回答必须给已知问题 ID |
| iWenCai 查询 | `search_a_share_iwencai` | 可选 `pywencai` 客户端 | 自然语言查询 |
| 复权因子 | `get_a_share_adjust_factors` | Sina realstock（零鉴权） | 单只 A 股，qfq/hfq |
| 估值历史 | `get_a_share_valuation_history` | baostock | 单只 A 股（非北交所）、日期区间；PE/PB/PS/PCF + 换手率/停牌/ST |
| 上市/退市日 | `get_a_share_listing_history` | baostock | 单只 A 股（非北交所）；上市日/退市日/状态 |
| 筹码分布 | `get_a_share_chip_distribution` | baostock OHLC+换手率本地推演 | 单只 A 股（非北交所）；获利比例/平均成本/成本区间（advisory heuristic） |
| 申万行业变迁史 | `get_sw_industry_history` | swsresearch 官方 xls | 市场级；每只股票每次行业调整一行（仅代码无中文名） |
| 社融 | `get_china_social_financing` | 人民银行官方 xls（零鉴权直连） | 市场级；月度社融增量表 |
| PMI | `get_china_pmi` | 国家统计局 easyquery（零鉴权直连） | 市场级；制造业/非制造业/综合 |

当前刻意不把下列内容伪装成已交付能力：

- “炸板率”需要可靠的盘中事件时间序列，当前涨停池只提供公开的日终事实，报告不会估算该指标。
- 财联社电报使用 `sign` 查询参数，但签名可在本地完全计算（`md5(sha1(按 key 排序后的 query string))`），无需 API key 或浏览器 token；`get_cls_telegraph` 作为 EastMoney 全球新闻的独立备份，任何失败都会返回类型化不可用。
- iWenCai 只在用户显式安装兼容的 `pywencai` 时启用；没有该客户端时返回不可用，系统不会抓取网页或制造查询结果。
- 复权因子是**补充端点**，不改主链路：mootdx OHLCV 保持不复权，需要跨除权日比价时由下游显式套因子（`qfq` 因子是除数、`hfq` 因子是乘数）。
- baostock 端（估值历史/上市退市日/筹码分布）**不支持北交所**（4/8/92/920 号段服务端拒绝），北交所标的在登录前即被拦截并返回类型化不可用，不静默返回空表。
- 申万行业变迁史只有官方**代码**（无中文名）；东财/通达信行业名体系不同、代码不通用，不能直接套用。

路由默认把上述数据归为可降级的 A 股补充能力：它们的失败不会使 OHLCV、财务报表或最终研究流程被误判为数据缺失。

## 官方披露与覆盖语义

- 中长期策略要求 `cninfo.announcements` 与 `exchange.announcements` 至少一个
  完整可用；不是把 CNINFO 固定为唯一必需来源。
- EastMoney 公告仍保留为旧工具的公开兼容备份，但使用非官方语义，不能
  映射成 `exchange.announcements`，也不能满足官方 required source group。
- CNINFO 完整性按“请求窗口已完整分页扫描”判断，不要求窗口第一天和最后
  一天刚好各有公告。分页预算耗尽为 partial。
- 权威端点完整查询后的空集是 `not_covered`；网络、限流或协议故障是
  `provider_unavailable`；非官方备份冒充官方载荷是 `invalid`。
- CNINFO 毫秒时间戳固定按 `Asia/Shanghai` 解释，再与冻结的 UTC cutoff
  比较，不依赖运行机器的本地时区。

## 新闻降级与凭据健康

- 公司新闻默认先尝试配置的 Tavily、Yahoo Finance、Alpha Vantage。对于 A 股，只有这些来源均无可用结果时，才会调用已有的上交所/深交所公开公告适配器；输出会明确标记 `china_exchange`，公告不能被当作完整市场新闻。可通过 `a_share_news_official_fallback_enabled: false` 关闭这条降级链。
- Tavily 可使用单个 `TAVILY_API_KEY`，也可使用逗号分隔的 `TAVILY_API_KEYS`。轮换和冷却按**单个 key**处理：429 冷却 60 秒，5xx 或网络错误冷却 20 秒；401/403 明确报不可用，不会尝试用另一把 key 绕过访问策略。
- 日志、进度事件和健康状态只保留 key 的不可逆短哈希，不记录原始凭据。所有 key 都在冷却时，新闻包会显示来源不可用，而不会制造空新闻或事实结论。
