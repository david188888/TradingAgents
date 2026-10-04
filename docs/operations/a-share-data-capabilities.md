# A 股补充数据能力

- **Status: Current**（current-state 文档；provider 路由变化时对照 `tradingagents/dataflows/registry.py` 与 `tradingagents/default_config.py` 校验）

这些接口是研究补充，而不是行情或基本面的替代。每个结果都会标明实际来源；空结果、SDK 缺失、字段变化、限流或未配置的供应商都会返回类型化的不可用状态，不能被解释为“没有事件”。

`evidence_v1` 使用独立的有界多源路由：东方财富/新浪身份、新浪三表、深交所日历、腾讯原始日线与新浪日期化因子优先，Tushare 备源。三种研究模式共用此路由；classic/catalyst 的供应商设置保持原语义。新浪字段保留合并范围、币种、实际披露日期及更新时间，按元值准入，不沿用旧文本适配器的亿元换算；不同供应商不合并来源家族。深交所日历只准入深市标的；历史因子无归档版本仍不可用。具体候选、配置与恢复边界见 [native 来源政策](evidence-research.md#evidence-and-workflow)。

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
| 互动易 | `get_a_share_interactive_questions`、`get_a_share_interactive_answers` | AKShare/CNINFO | **仅深市**；沪市代码快速失败并指向 `get_a_share_sse_e_interaction`，不会静默返回“无提问” |
| 上证e互动 | `get_a_share_sse_e_interaction` | 上交所官方平台（sns.sseinfo.com） | 单只沪市 A 股或全市场；深市/北交所代码直接拒绝 |
| iWenCai 查询 | `search_a_share_iwencai` | 可选 `pywencai` 客户端 | 自然语言查询 |
| 复权因子 | `get_a_share_adjust_factors` | Sina realstock（零鉴权） | 单只 A 股，qfq/hfq |
| 估值历史 | `get_a_share_valuation_history` | baostock | 单只 A 股（非北交所）、日期区间；PE/PB/PS/PCF + 换手率/停牌/ST |
| 上市/退市日 | `get_a_share_listing_history` | baostock | 单只 A 股（非北交所）；上市日/退市日/状态 |
| 筹码分布 | `get_a_share_chip_distribution` | baostock OHLC+换手率本地推演 | 单只 A 股（非北交所）；获利比例/平均成本/成本区间（advisory heuristic） |
| 申万行业变迁史 | `get_sw_industry_history` | swsresearch 官方 xls | 市场级；每只股票每次行业调整一行（仅代码无中文名） |
| 业绩预告 | `get_a_share_earnings_forecast` | EastMoney datacenter（`RPT_PUBLIC_OP_NEWPREDICT`） | 市场级或单只 A 股、报告期；一次预告按指标拆多行 |
| 机构调研 | `get_a_share_institution_survey` | EastMoney datacenter（`RPT_ORG_SURVEYNEW`） | 市场级或单只 A 股、公告日区间；`detail` 切换为一家机构一行 |
| 股票回购 | `get_a_share_share_buyback` | EastMoney datacenter（`RPTA_WEB_GETHGLIST_NEW`） | 市场级或单只 A 股、进度；一个方案一行，方案与已实施分列不合并 |
| 股权质押 | `get_a_share_equity_pledge` | EastMoney datacenter（`RPT_CSDC_LIST`，中国结算周度） | 单只 A 股**或**单个统计日，二者互斥；仅沪深，北交所代码直接拒绝 |
| 新股申购日历 | `get_a_share_ipo_calendar` | EastMoney datacenter（`RPTA_APP_IPOAPPLY`） | 市场级；含尚未申购的排期，定价前发行价为 None |
| ST 名单 | `get_a_share_st_stock_list` | EastMoney clist（沪深风险警示板 + 北交所全表），baostock 兜底 | 市场级当日快照；两侧集合任一为空即报错 |
| 交易日历 | `get_a_share_trading_calendar` | 深交所官方整月日历 | 单月；月份不完整或交易日标志异常直接报错 |
| 两融官方备胎 | `get_a_share_margin_trading_backup` | 上交所/深交所官方，一次一所 | 交易所 + 交易日；不覆盖北交所，代码号段与交易所不符即拒绝 |
| 新浪研报列表 | `get_sina_research_reports` | 新浪财经研报列表 | 市场级或单只 A 股；**不含评级与目标价**，北交所代码需 `bj` 前缀 |
| 社融 | `get_china_social_financing` | 人民银行官方 xls（零鉴权直连） | 市场级；月度社融增量表 |
| PMI | `get_china_pmi` | 国家统计局 easyquery（零鉴权直连） | 市场级；制造业/非制造业/综合 |

### EastMoney datacenter 严格性

事件驱动层（业绩预告/机构调研/回购/质押/新股日历）与 ST 名单按上游 v3.9.0 的严格约定实现，与早期的单页适配器不同：

- 必须检查响应 `code`；仅“第 1 页 `code=9201`”表示确实没有数据，其他错误码一律抛类型化不可用，不再把风控/参数错误洗成“没有事件”。
- 翻页中途出现空页、非末页不满页、`pages`/`count` 变化、或最终条数与 `count` 不符都报错；不把部分结果当完整结果。
- `sortColumns` 与 `sortTypes` 个数必须一致（否则东财返回 9501）。
- 返回行必须逐行复核确实满足请求的个股/日期条件，否则报错而不是返回别的标的或报告期。
- 完整市场查询返回 0 行视为接口异常；带个股/日期条件返回 0 行才是“确实没有”。

> 早期已移植的 datacenter 适配器（大宗交易、股东户数、解禁、龙虎榜、日龙虎榜、融资融券）**已全部回填**同一套严格契约，并返回带 coverage 的结果。
> 各能力行数上限：大宗交易 500、股东户数 200、解禁 500、龙虎榜 500（榜单与买卖席位各一次）、日龙虎榜 1500、融资融券 2000；
> 龙虎榜由三个子查询拼成，**只有当每个子查询都完整时整体才算 complete**，否则降级为 partial/unknown 并带 `subquery_incomplete`。
>
> 仍是单页、不检查响应 `code` 的是 **push2 / push2ex** 系（行业排名、板块资金流、概念归属、涨停池、监控池、异动）——那是另一套响应结构，需要单独一轮。

当前刻意不把下列内容伪装成已交付能力：

- “炸板率”需要可靠的盘中事件时间序列，当前涨停池只提供公开的日终事实，报告不会估算该指标。
- 财联社电报使用 `sign` 查询参数，但签名可在本地完全计算（`md5(sha1(按 key 排序后的 query string))`），无需 API key 或浏览器 token；`get_cls_telegraph` 作为 EastMoney 全球新闻的独立备份，任何失败都会返回类型化不可用。
- iWenCai 只在用户显式安装兼容的 `pywencai` 时启用；没有该客户端时返回不可用，系统不会抓取网页或制造查询结果。
- 复权因子是**补充端点**，不改主链路：mootdx OHLCV 保持不复权，需要跨除权日比价时由下游显式套因子（`qfq` 因子是除数、`hfq` 因子是乘数）。
- baostock 端（估值历史/上市退市日/筹码分布）**不支持北交所**（4/8/92/920 号段服务端拒绝），北交所标的在登录前即被拦截并返回类型化不可用，不静默返回空表。
- 申万行业变迁史只有官方**代码**（无中文名）；东财/通达信行业名体系不同、代码不通用，不能直接套用。

路由默认把上述数据归为可降级的 A 股补充能力：它们的失败不会使 OHLCV、财务报表或最终研究流程被误判为数据缺失。

## 「完整查过且确实没有」与「取数失败」

对筛查类查询，这两件事必须可区分：把限流读成"这家公司没有披露业绩预告"是一项错误的否定发现。本仓库用既有的 coverage 契约表达，而不是靠报告措辞：

- `CoveredText` 是 `str` 子类，携带 `SourceCoverageV1`。老调用方当字符串用照旧；`data_meta_tools` 会把 `.coverage` 带进结果信封。
- `completeness == "complete"` 且 `item_count == 0` ⟹ **来源走完了整个查询，确实没有命中**。
- 抛 `ChinaDataUnavailableError` ⟹ **取数失败、被限流或响应格式变了**，绝不等于"没有"。
- `completeness == "partial"` / `"unknown"` ⟹ 有数据但不完整，`degradations` 写明原因（`row_cap_truncated`、`pagination_not_proven`、`no_source_reported_total` 等）。

基类 `SourceCoverageV1` 默认**不允许** `complete` 搭配零条记录（对文档/载荷集合类能力这是正确约束）。筛查类能力使用 `ScreeningCoverageV1`：它显式覆写两个默认关闭的钩子，并要求 `query_complete == (pagination_exhausted is True)`——即分页必须被走完、来源自报总数必须与实际读到的行数核对一致，否则只能是 `partial`/`unknown`。

适用范围：东财 datacenter 系（事件驱动五端点、大宗交易、股东户数、解禁、龙虎榜、日龙虎榜、融资融券）、ST 名单、新浪研报列表。东财 **push2 / push2ex** 系（行业排名、板块资金流、概念归属、涨停池、监控池、异动）尚未纳入，仍可能把结构变化洗成空表。

新浪没有可核对的总数或分页终点，有记录的页面仅为 `partial / no_source_reported_total`。其「没有找到相关内容」页面与限流响应相同；间隔重试后仍为空页会返回 `ambiguous_empty_response` 不可用，不能证明没有研报。线程内的并发调用共享请求锁与单调时钟间隔，失败也计入间隔。

## 研究日期与最新数据

Analyst bundle 中新增的业绩预告、回购、质押、IPO 日历、上证e互动和新浪研报接口只提供实时/最新查询，没有历史载荷 vintage。六项工具仅在研究截止日等于当前上海日期时调用供应商；历史、未来或非法日期在 dispatch 前返回带来源的不可用状态。bundle 的 `as_of` 标签不能将今天的数据变成历史证据。机构调研仍按 `NOTICE_DATE` 公告窗口过滤；这项筛选本身不构成不可变历史快照证明。直接调用底层接口仍是最新数据查询，调用方负责资格校验。

腾讯周线/月线分页以最早已返回 bar 所在日历周期的前一周期末日作为下一游标，避免短交易周与不同月长漏 bar；日线仍逐日回退。这个分页覆盖检查不提供历史复权因子 vintage，也不改变 catalyst 对未验证 qfq 的拒绝。`apply_adjust` 拒绝非有限/非正因子和非有限价格计算结果，但显式换算不等于来源或 PIT 资格证明。

新增事件/官方能力可由已注册的 meta-tool 关键词或直接路由触达，目前没有自动加入 supplement prefetch 或 bounded catalyst 能力。增加端点不自动增加合格证据。

## 官方披露与覆盖语义

- 中长期策略要求 `cninfo.announcements` 与 `exchange.announcements` 至少一个
  完整可用；不是把 CNINFO 固定为唯一必需来源。
- EastMoney 公告仍保留为旧工具的公开兼容备份，但使用非官方语义，不能
  映射成 `exchange.announcements`，也不能满足官方 required source group。
- CNINFO 完整性按“请求窗口已完整分页扫描”判断，不要求窗口第一天和最后
  一天刚好各有公告。分页预算耗尽为 partial。
  显式 `hasMore=true` 优先于矛盾的 `totalpages`，继续在预算内分页；
  返回项若显式声明了其他证券代码，则拒绝整次结果。
- 权威端点完整查询后的空集是 `not_covered`；网络、限流或协议故障是
  `provider_unavailable`；非官方备份冒充官方载荷是 `invalid`。
- CNINFO 毫秒时间戳固定按 `Asia/Shanghai` 解释，再与冻结的 UTC cutoff
  比较，不依赖运行机器的本地时区。

## 新闻降级与凭据健康

- 公司新闻默认先尝试配置的 Tavily、Yahoo Finance、Alpha Vantage。对于 A 股，只有这些来源均无可用结果时，才会调用已有的上交所/深交所公开公告适配器；输出会明确标记 `china_exchange`，公告不能被当作完整市场新闻。可通过 `a_share_news_official_fallback_enabled: false` 关闭这条降级链。
- Tavily 可使用单个 `TAVILY_API_KEY`，也可使用逗号分隔的 `TAVILY_API_KEYS`。轮换和冷却按**单个 key**处理：429 冷却 60 秒，5xx 或网络错误冷却 20 秒；401/403 明确报不可用，不会尝试用另一把 key 绕过访问策略。
- 日志、进度事件和健康状态只保留 key 的不可逆短哈希，不记录原始凭据。所有 key 都在冷却时，新闻包会显示来源不可用，而不会制造空新闻或事实结论。

## 上游基准与同步状态

本仓库的 A 股补充适配器是**手写移植**，不是运行时依赖：上游
[simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) 的
`SKILL.md` 是 Markdown 内嵌 Python，无法 import，只作为端点、参数与字段的
参考。安装整套工具包不是运行要求。

- **移植基准**：上游 **v3.7.1**（2026-08-20）。
- **本次同步目标**：上游 **v3.10.0**（2026-09-22），覆盖 v3.7.2 / v3.8.0 / v3.9.0 / v3.10.0。
- 上游 v3.10.0 把 Layer 1 重新编号（mootdx 由 §1.1 变为 §1.7，腾讯行情由 §1.2 变为 §1.1，新浪复权因子由 §1.4 变为 §1.6，逐笔/腾讯 K 线等为新增）。**函数名与签名未变**，本仓库已按新编号刷新注释。

本次同步采纳的内容：

- **#52 mootdx 验活分流**：`tdx_client()` 新增 `check='bars'|'finance'`，客户端缓存与熔断器按验活类别分离。2026-09 起通达信公开服务器的行情命令返回空表，而财务快照与 F10「最新提示」仍可用；此前财务/F10 走同一个 K 线探针，会被误判为全部不可达。非 `std` 市场跳过验活（探针样本是 A 股代码）。
- **#55 聚宽后缀**：`strict_ticker_code` / `normalize_ticker_symbol` 接受 `600519.XSHG` / `000001.XSHE`，后缀与号段矛盾仍然拒绝；新增 `to_joinquant_symbol`。
- **事件驱动层**（上游 §14）：业绩预告、机构调研、股票回购、股权质押、新股申购日历。
- **缺口补齐**：ST 名单、深交所交易日历、上交所/深交所官方两融备胎、上证e互动、新浪研报列表。
- **互动易范围更正**：巨潮互动易只覆盖深市；沪市代码改为快速失败并指向上证e互动，不再静默返回“无提问”。

本次刻意不同步的内容（保持现状的明确决定，而非遗漏）：

- **Layer 13 期货与大宗商品**（期货/期权日行情、持仓排名、A50、上金所）与 **Layer 15 可转债**：不在本仓 A 股股票研究的范围内。
- **§1.3 通达信盘后包**、**§1.4 腾讯逐笔**：现有 tushare 日线与腾讯日线已覆盖研究所需的 OHLCV，逐笔/全市场盘后包没有下游消费者。
- **腾讯 K 线只做日/周/月**：上游 §1.2 还提供 1–60 分钟线、hfq 与三域名轮换；本仓注册了日/周/月 × raw/qfq 六个能力，周期是能力身份的一部分（`get_a_share_kline_weekly` 等），不允许由日线供应商顶替。
- **mootdx 服务器列表保持本仓实测版本**：与上游列表不同（上游为 2026-06 验证），本次无联网实测，不替换。`tdx_client()` 增加了上游的 `bestip` / 裸 factory 回退阶段作为列表过期时的恢复路径。
- **push2 / push2ex 系适配器未回填**：行业排名、板块资金流、概念归属、涨停池、监控池、异动仍是单页且不检查响应结构，`data.get("diff") or []` 这类写法会把结构变化洗成空表。见上文「EastMoney datacenter 严格性」。
- **北交所 B 股/老号段等 §-only 边界**：仅在本次新增的适配器中实现。
