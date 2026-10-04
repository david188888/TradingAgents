# a-stock-data v3.10.0 同步与合并参考

- **Status: Historical**
- **Do not use this document as evidence of current implementation behavior.** 当前行为的事实源是代码、passing tests，以及 [A 股补充数据能力](../../operations/a-share-data-capabilities.md)（`Status: Current`）。本文是**分支合并与交接记录**：说明这条分支改了什么、怎么合、合完怎么验、以及哪些地方是刻意的决定而不是遗漏。

2026-10-02 已将分支 tip `4b2fcb8` 合入本地 `codex/research-data-integration-20261002`，合并提交 `78038c6`。原有研究/Reader 改动保存在 `90d0199`。本文以下内容保留分支合并前的交接背景；实际整合、追加修复和同环境验收见[整合验收记录](2026-10-02-research-data-integration-acceptance.md)。原推荐命令含 stash，仅为旧交接文本，本次没有手动 stash 或重置工作区。

## 1. 这条分支是什么

| 项 | 值 |
|---|---|
| 分支 | `feat/a-stock-data-v3.10-sync` |
| 基线 commit | `b68fee8`（`main`，2026-09-30 Merge pull request #9） |
| worktree | `.claude/worktrees/a-stock-data-v310`（`.claude/worktrees/` 已被 `.git/info/exclude` 排除，不会污染 `git status`） |
| 上游基准 | 从 **v3.7.1** 对齐到 **v3.10.0**（覆盖 v3.7.2 / v3.8.0 / v3.9.0 / v3.10.0） |
| 上游仓库 | <https://github.com/simonlin1212/a-stock-data> |

### 提交构成

按时间顺序（合并时保持分段，便于逐条审阅与回滚）。前六条哈希稳定；末条是分支 tip，用下方命令取实际值：

| commit | 内容 |
|---|---|
| `cb2ab4f` | 修 #52 mootdx 验活分流、#55 聚宽后缀、F10 失效类别、互动易沪市盲区；刷新 Layer 1 编号；能力文档记录上游基准 |
| `0599e8a` | 新增 `apply_adjust`（复权因子换算）+ 修 Sina 复权因子对 `000001.XSHG` 的静默错票 |
| `105f38f` | F10 不再把 dict 响应字符串化当披露正文；`pyproject` 补 `openpyxl`/`xlrd` |
| `cec83e6` | 事件驱动层五端点 + ST 名单 + 深交所日历 + 官方两融 + 上证e互动 + 新浪研报；registry/default_config/data_meta_tools 接线 |
| `41cf487` | `coverage.py` 规范扩展（`ScreeningCoverageV1`）+ 腾讯周线/月线 |
| `f10eba5` | 六个 `(period, adjust)` 能力互不相同的注册断言 |
| 分支 tip（`git log -1 --format=%h main..feat/a-stock-data-v3.10-sync`） | 东财 datacenter 严格性回填六个适配器 + coverage 返回；新浪研报 coverage；移除已无引用的宽松 helper；事件层与回填的测试 |

**为什么会有这条分支。** 本机安装的 skill（`~/.claude/skills/a-stock-data/SKILL.md`）与上游 tag v3.7.1 **逐字节相同**，而上游已到 v3.10.0。核对后结论是：v3.7.1→v3.10.0 共有的 90 个函数里只有 13 个实现有变，其中真正影响本仓库的只有 3 条（见 §3.1），其余是 Layer 1 章节重编号与文档字符串；主要工作量在 v3.8–v3.10 新增的 4 个层、34 个函数。

**重要：本仓库不 vendor 上游。** 上游 `SKILL.md` 是 Markdown 内嵌 Python，无法 import，只作为端点/参数/字段的参考。本分支延续「手写移植到 `tradingagents/dataflows/` 现有 registry + typed-error 架构」的做法。

## 2. 合并前必须知道的三件事

1. **基线工作区不干净。** `main` 工作区有 23 个未提交文件（估值/价格统计那条线在飞），其中 `tradingagents/default_config.py` 与 `README.md` 与本分支**改到了同一个文件**。合并前请先决定这些改动的归宿。
2. **`default_config.py` 大概率冲突。** 本分支在 `data_vendors` 与 `tool_vendors` 两处各插入了一组新能力；如果基线在那附近也改过，需要手工合并（两组改动在语义上正交，直接两边都保留即可）。
3. **本分支有两个提交改动了 `coverage.py`（规范文件）。** 这是刻意的，见 §5。合并时不要让「恢复成原样」的改法把它冲掉。

## 3. 改了什么

### 3.1 修复已移植代码的真实缺陷

| # | 上游依据 | 问题 | 处理 |
|---|---|---|---|
| 1 | #52 / v3.9.0 | `tdx_client()` 只用 K 线验活。2026-09 起通达信行情命令返回空表而**财务快照与 F10 仍可用**，导致 `get_fundamentals_mootdx` / `get_a_share_f10` 在当前网络下永久不可用 | 按 `check='bars'\|'finance'` 分流；客户端缓存与熔断器按类别隔离；补上游的 `bestip` / 裸 factory 回退阶段；非 `std` 市场跳过验活 |
| 2 | #55 / v3.9.0 | `.XSHG` / `.XSHE` 全仓缺失 | `strict_ticker_code` / `normalize_ticker_symbol` 接受聚宽后缀，号段矛盾仍拒绝；新增 `to_joinquant_symbol` |
| 3 | v3.9.0 §6.2 | F10 对已失效类别会把 mootdx 返回的 dict `str()` 成"公司披露正文" | 先读服务端真实类别表（advisory，F10C 不可用时不阻断），非文本回复按格式变更报错 |
| 4 | v3.9.0 §1.6 | 复权因子端点存在，但"由下游显式套因子"的换算函数**根本没实现** | 新增 `apply_adjust`（qfq 是除数、hfq 是乘数，方向传错不报错所以必须显式） |
| 5 | #55 | `get_a_share_adjust_factors` 把 `000001.XSHG`（上证指数）拼成 `sz000001`（平安银行） | Sina 前缀识别接受聚宽后缀 |
| 6 | v3.9.0 §10.1 | 巨潮互动易只覆盖深市，沪市原先静默返回"无提问" | 沪市代码快速失败并指向上证e互动；新增上证e互动源 |

### 3.2 新增能力（11 个路由方法）

**事件驱动层**（东财 datacenter）：`get_a_share_earnings_forecast`、`get_a_share_institution_survey`、`get_a_share_share_buyback`、`get_a_share_equity_pledge`、`get_a_share_ipo_calendar`。

**缺口补齐**：`get_a_share_st_stock_list`、`get_a_share_trading_calendar`、`get_a_share_margin_trading_backup`、`get_a_share_sse_e_interaction`、`get_a_share_research_reports_sina`。

**腾讯周线/月线**：`get_a_share_kline_weekly`、`get_a_share_kline_weekly_qfq`、`get_a_share_kline_monthly`、`get_a_share_kline_monthly_qfq`。

> `holder_trades`（上游 §14.3）**没有重复实现**：本仓库既有的 `china_capital_flow.get_a_share_insider_trades` 已经读同一张 `RPT_SHARE_HOLDER_INCREASE`。

### 3.3 东财 datacenter 严格性回填

早期适配器（大宗交易、股东户数、解禁、龙虎榜、日龙虎榜、融资融券）原先只请求单页、且**不检查响应 `code`**，把风控/参数错误洗成"没有数据"。现已全部改用共享的严格分页器（`eastmoney.em_datacenter_strict`）：

- 只有**第 1 页 `code=9201`** 才算"来源确实没有"，其他非零 `code` 一律报错并带上 code + message；
- 第 2 页起出现 `9201`、空页、非末页不满页、`pages`/`count` 中途变化、最终条数与 `count` 不符，全部报错；
- `sortColumns` / `sortTypes` 元素个数必须先校验（否则东财返回 9501）；
- `max_rows` 只在来源自报 `count` 超过上限时截断，否则走完分页并核对总数；
- 返回行逐行复核确实满足请求的个股/日期条件；
- 翻页出现完全重复行视为排序不唯一，报错。

各能力行数上限：大宗交易 500、股东户数 200、解禁 500、龙虎榜 500、日龙虎榜 1500、融资融券 2000。

## 4. 目录与文件地图

**新增的生产代码**

| 文件 | 内容 |
|---|---|
| `tradingagents/dataflows/a_share_events.py` | 事件驱动层五个端点 + ST 名单 |
| `tradingagents/dataflows/a_share_official.py` | 深交所交易日历、沪深官方两融、上证e互动 |
| `tradingagents/dataflows/sina_research.py` | 新浪研报列表（东财之外的第二研报源） |

**修改的生产代码**

`coverage.py`（规范扩展，见 §5）、`eastmoney.py`（共享严格分页器 + 两融回填）、`china_specialty_em.py`（五个老适配器回填）、`mootdx_provider.py`、`tencent_kline.py`、`ticker_utils.py`、`china_capabilities.py`、`a_stock_v37.py`、`tencent_provider.py`、`registry.py`、`default_config.py`、`agents/utils/data_meta_tools.py`、`pyproject.toml`（补 `openpyxl` / `xlrd`）、`README.md`、`README.zh-CN.md`。

**新增测试**（全部离线，无联网）

`tests/test_mootdx_finance_probe.py`、`tests/test_tencent_kline_periods.py`、`tests/test_a_share_events.py`、`tests/test_a_share_official.py`、`tests/test_sina_research.py`。

**修改测试**：`test_mootdx_tdx1_circuit_breaker.py`、`test_a_stock_data_adapters.py`、`test_a_stock_v37.py`、`test_china_specialty_em.py`、`test_eastmoney.py`。

## 5. 规范改动：为什么 `coverage.py` 必须改

这是本分支**唯一**触碰规范文件的地方，也是最容易被后续 agent 误改回去的地方。

`SourceCoverageV1` 原本规定 `completeness="complete"` 必须至少有一条记录：

```python
if self.completeness == "complete":
    if self.item_count == 0:
        raise ValueError("complete coverage requires at least one retained item")
```

对"文档/载荷集合"类能力这是对的：空载荷不是可用结果。但对**筛查类**查询恰好是反的——"这家公司在窗口内没有披露业绩预告"和"接口被限流"是两件不同的事实，而旧规则把两者都压成 `unavailable`，读者会把取数失败当成一项否定发现。

本分支的处理：

1. 在基类加两个**默认返回 `False`/`True` 的可覆写钩子**（`_allows_complete_without_items`、`_requires_observed_window_for_complete`）。默认值保持原有语义，**所有既有子类与消费方的行为逐字节不变**。
2. 新增 `ScreeningCoverageV1`，显式覆写这两个钩子，并新增两个字段：
   - `query_complete`：只有当来源分页被走完、且自报总数与实际读到的行数核对一致时才能为真；
   - `requested_scope`：搜索范围的可读描述（"没有命中"只有配上搜过什么才有意义）。
3. `ScreeningCoverageV1` 自身强制：`query_complete == (pagination_exhausted is True)`；`complete` 必须 `query_complete` 且**不得**携带 degradation code；`unavailable` 不得 `query_complete`。

**消费方怎么看**：`CoveredText` 是 `str` 子类，因此老代码当字符串用照旧；`data_meta_tools._execute` 已经会读取 `.coverage` 并把覆盖信息带进结果信封。所以：

- `result.coverage.completeness == "complete"` 且 `item_count == 0` ⟹ **来源查完了，确实没有**；
- 抛 `ChinaDataUnavailableError` ⟹ **取数失败／格式变了**，绝不等于"没有"；
- `completeness == "partial"` / `"unknown"` ⟹ 有数据但不完整，`degradations` 里写明原因（如 `row_cap_truncated`、`pagination_not_proven`）。

**不要**把这条规则简化回基类，也**不要**给 `ScreeningCoverageV1` 传 `query_complete=True` 而没有真正走完分页。

## 6. 怎么合

推荐顺序（在 `main` 检出目录里）：

```bash
# 0. 先处理基线未提交改动（提交、stash 或另开 worktree）
git -C /Users/david/codespace/TradingAgents status --short

# 1. 看清这条分支的实际内容
git log --oneline main..feat/a-stock-data-v3.10-sync
git diff --stat main...feat/a-stock-data-v3.10-sync

# 2. 合并（默认 merge，保留分段提交便于审阅与回滚）
git merge feat/a-stock-data-v3.10-sync

# 3. 冲突预判
#    - tradingagents/default_config.py  ← 期望冲突，两边新增组都保留
#    - README.md / README.zh-CN.md      ← 期望冲突（同一段附近行号），取双方内容
#    - 其它文件预期不冲突
```

**本分支的提交是分段的**，建议按原样保留，合并后可以逐条回滚；不要 rebase 成单个提交，否则 `coverage.py` 的规范扩展会与事件层改动混在一起，审阅时无法分辨。

## 7. 合完怎么验

```bash
cd /Users/david/codespace/TradingAgents

# 公共门槛（fresh clone 契约）
python scripts/check_agent_docs.py
ruff check tradingagents cli scripts/check_agent_docs.py

# 本地脚手架（存在时才跑）
python -m pytest -q -p no:randomly
```

**判定标准是"失败集合不增大"，不是"全绿"。** 本机当前基线本身就是**红的**：`main` 在 `b68fee8` 上全量跑是 **52 failed / 2310 passed**，其中包含环境相关的 LLM/provider 测试（`test_ollama_base_url`、`test_temperature_config`、`test_openai_reasoning_effort`、`test_minimax`、`test_web_cli`）以及文档里已记录的 graph 路由与 runtime 指纹类失败。

正确做法是**在同一棵树上先测基线再比对**：

```bash
# 基线失败集合
git stash push -u        # 或在一个干净的 worktree / detached HEAD 上
python -m pytest -q -p no:randomly --tb=no 2>&1 | grep '^FAILED' | sort > /tmp/base.txt
# 合并后失败集合
python -m pytest -q -p no:randomly --tb=no 2>&1 | grep '^FAILED' | sort > /tmp/merged.txt
comm -13 /tmp/base.txt /tmp/merged.txt    # 必须为空 = 无回归
```

本分支的实测：基线 `b68fee8` 为 **52 failed / 2310 passed**，本分支为 **52 failed / 2469 passed**，`comm` 两侧为空——**失败集合逐条相同，零回归，新增 159 个测试全绿**。

> 注意：仓库里 `docs/superpowers/plans/baseline-pytest-failures.md` 记录的「12 failed」是在 conda 环境（Python 3.13.13 + pytest 9.0.3）测的，与 `.venv` 下的 52 不一致。**请用同一环境现测现比**，不要拿那份旧数字当门槛。

## 8. 刻意不做的事（是决定，不是遗漏）

| 项 | 决定 | 理由 |
|---|---|---|
| 上游 Layer 13 期货/大宗商品（期货/期权日行情、持仓排名、A50、上金所） | **不做** | 与本仓库 A 股股票研究定位无关（用户明确） |
| 上游 Layer 15 可转债 | **不做** | 同上；若要加，只需照 `a_share_events.py` 的模式新增一个东财 datacenter 适配器 + 一个路由方法 |
| 上游 §1.3 通达信盘后包、§1.4 腾讯逐笔 | **不做** | 现有 tushare 日线与腾讯日/周/月线已覆盖研究所需 OHLCV；无下游消费者 |
| 腾讯分钟线（m1/m5/m15/m30/m60）、hfq | **不做** | 用户只要求周线/月线 |
| 腾讯 K 线的三域名轮换 | **不做** | 本分支只加了 period，未改主机策略 |
| mootdx 服务器列表替换为上游列表 | **不做** | 本机列表有 2026-07 实测依据；上游列表是 2026-06 验证且本次无联网实测。已补 `bestip`/裸 factory 回退作为列表过期的恢复路径 |
| 东财 **push2 / push2ex** 系适配器（行业排名、板块资金流、概念归属、涨停池、监控池、异动）的严格化 | **不在本次范围** | 用户确认范围是"东财 datacenter 类 + 事件类"。这批走的是另一套响应结构（`rc`/`data.diff`），需要单独一轮 |
| 腾讯 qfq 遇到"未除权标的只回原始 key"时按上游放行 | **保持拒绝** | 本仓库 2026-09-29 实测 688981.SH 出现该形态并选择保守拒绝；上游 v3.9.0 认为未分红标的 qfq≡raw 可以放行。两者冲突，本分支保留更保守的本地行为，不静默放宽价格口径 |

## 9. 未决事项（留给下一位）

1. **push2 / push2ex 系适配器的诚实性**：`data.get("diff") or []` 这类写法仍会把结构变化洗成空表（本分支只在 datacenter 系修掉了）。
2. **`research/a_share_supplement.py` 的能力预算表**没有加入新能力，因此新事件源目前只能通过 `data_meta_tools` 的关键词选择或直接 `route_to_vendor` 触达，不参与 prefetch。加入会改变 runtime 指纹（该类测试当前已是红的），需要单独决策。
3. **分钟线与 hfq**：若研究需要更细粒度或后复权，腾讯路径已参数化（`period`），补 `m*` 需要新的 key 与"分钟线只有不复权"的约束。
4. **北交所**：腾讯 K 线对北交所仍只返回 1 根，本分支未加显式拒绝（上游是直接 `ValueError`）。
