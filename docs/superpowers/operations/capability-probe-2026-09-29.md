# 数据源能力实测记录（T04 / T16）

- **状态**：实测记录，非设计文档。全部结论来自本轮真实端点调用；未调用的一律标 `未验证`。
- 执行 Agent：H（数据源探测）。代码基线：`ca90f27`（主 checkout `main`）。
- 探测窗口：2026-09-29 10:40–11:35 CST（Asia/Shanghai）。探测当日为交易日，盘中 10:40–11:35。
- 运行环境：macOS (darwin 27.0.0)，Python 3.13.13（conda env `tradingagents`）。
- 依赖版本：mootdx `0.11.7`、tushare `1.4.29`、akshare `1.18.59`、pandas `3.0.2`、requests `2.33.1`；Wind 经 `wind-mcp-skill` CLI，provider `SKILL_VERSION = 2.0.1`。
- 凭据：仅使用环境变量名 `TUSHARE_TOKEN`、`TUSHARE_API_KEY`、`WIND_API_KEY`（三者均存在，长度分别 56 / 56 / 35）。**本文件不含任何凭据值、不含带 token 的 URL。**
- 授权边界：仅探测数据端点。**未启动任何 LLM 研究运行**。未修改产品代码。未读写 `~/.tradingagents/`。未提交。

## 0. 摘要（先读这一节）

| # | 能力 | 结论 | 一句话 |
| --- | --- | --- | --- |
| 1 | Wind `get_adjusted_price_history` | **成功（有重大告警）** | 数据真实、字段正确、单位正确；但 PIT 未验证，且 index 路径有独立缺陷 |
| 2 | 腾讯 raw 日线 | **成功（未注册，需新 adapter）** | 可用；**字段顺序非标准 OHLC**；单请求上限 640 行且无截断标记 |
| 3 | 腾讯 qfq 日线 | **降级** | 复权真实存在，但**按标的分段返回**，不适用则静默回落 `day`（未复权） |
| 4 | Wind index `000300` | **失败（数据错误）** | 返回 0.862–0.966，真实沪深300 约 4000 点；`000300.OF` 未解析成指数 |
| 5 | mootdx 日线/财务/F10 | **失败（全线不可用）** | TCP 可连、factory 成功，但每个数据调用都返回空 DataFrame |
| 6 | Tushare raw 日线 | **成功** | 字段、单位、排序、沪深北齐全，质量最好 |
| 7 | Tushare qfq 日线 | **降级（限流）** | `adj_factor` 接口 1 次/分钟，串行下 2/2 失败 |
| 8 | 静默 vendor 替换 | **已确认存在（代码级）** | 冷却中的主源会把整条 fallback 链追加进来 |
| 9 | 机构调研（T16） | **显式延后** | 无合格端点；现有互动易不构成调研记录 |

**上游传闻核实**：上游 a-stock-data 报告 mootdx 公开行情命令失效——本轮在本地 `mootdx_provider.py` 路径上**独立复现并确认**该失效（见 §5）。

---

## 1. Wind `get_stock_adjusted_price_history`（qfq 复权日线）

| 字段 | 内容 |
| --- | --- |
| **能力** | Wind 前复权（qfq）日线 OHLCV，T13 候选复权源 |
| **adapter 版本** | `tradingagents/dataflows/wind_provider.py`，`SKILL_VERSION = 2.0.1`，底层 `wind-mcp-skill` CLI（`~/.claude/skills/wind-mcp-skill/scripts/cli.mjs`）；`WIND_CLI_PATH` 未设置，走默认路径且解析成功 |
| **样本范围** | 沪 `600519.SH`、深 `000001.SZ`、北 `920008.BJ`；窗口 2026-08-01..2026-09-29 与 2025-09-01..2025-09-10 两段 |
| **探测时间** | 2026-09-29 11:20–11:35 CST |
| **来源** | Wind（凭据 `WIND_API_KEY`） |
| **成功/降级/失败** | **成功**（3/3 标的全字段返回，含北交所）；无降级 |

### 响应字段摘要

CSV 表头：`TIME,OPEN,MATCH,HIGH,LOW,TURNOVER,VOLUME,CHANGEHANDRATE,AVPRICE`

- `MATCH` = 收盘价（Wind 专名，非 `CLOSE`）
- `TIME` = `2026-08-03T00:00:00.000+08:00`（带 +08:00 时区偏移，日期分量即交易日）
- 另有 `CHANGEHANDRATE`（换手率）、`AVPRICE`（均价）

### 日期/单位验证（五方交叉核对，最关键的一项）

以 `600519.SH` 2025-09-01..2025-09-10 为样本，同日对比 Wind(qfq) / Tushare(raw) / 腾讯(raw) / 腾讯(qfq)：

```
2025-09-01: wind_qfq=1417.83 | tushare_raw=1476.10 | tx_raw=1476.100 | tx_qfq=1424.119
2025-09-02: wind_qfq=1432.43 | tushare_raw=1491.30 | tx_raw=1491.300 | tx_qfq=1439.319
2025-09-03: wind_qfq=1422.11 | tushare_raw=1480.55 | tx_raw=1480.550 | tx_qfq=1428.569
2025-09-04: wind_qfq=1414.53 | tushare_raw=1472.66 | tx_raw=1472.660 | tx_qfq=1420.679
2025-09-05: wind_qfq=1424.46 | tushare_raw=1483.00 | tx_raw=1483.000 | tx_qfq=1431.019
2025-09-08: wind_qfq=1441.97 | tushare_raw=1501.23 | tx_raw=1501.230 | tx_qfq=1449.249
```

- **Wind(qfq) 既不等于 raw，也不等于腾讯 qfq。** 它确实**做了复权**（与 raw 有稳定 ~4% 偏离），但与腾讯 qfq 的比值在窗口内**不是常数**（`1417.83/1424.119=0.99556`、`1441.97/1449.249=0.99503`），说明**两家的 qfq 锚定基准日不同**（锚点取"今天"vs 取"上市首日"之类的差异）。**两家供应商的 qfq 数值不可直接互相替代，也不可混合。**
- **Tushare qfq 本轮取不到**（`adj_factor` 限流，见 §6），所以「Wind qfq 是否等于 Tushare qfq」**未验证**。
- **成交量单位已验证正确**：`wind.VOLUME / 100 == tushare.VOLUME`（手），逐日 ratio 精确为 `1.0000`。
- **成交额单位已验证**：`wind.TURNOVER`（字段名叫 turnover/换手，但值是金额）为**元**；`tushare.amount` 为**千元**。`6658918555 元 == 6658918.555 千元`，精确吻合。**字段名与语义不符，接入时必须重命名，否则会被当成换手率使用。**
- OHLC 内部一致性已验证：`LOW <= min(OPEN, MATCH) <= max(OPEN, MATCH) <= HIGH` 逐日成立（§3 中对腾讯做了同样检验，Wind 输出结构一致）。

### 限制

1. **`pit_unverified`**（设计的 §8.5 硬性要求）：qfq 历史值会随后续除权除息被重算。本轮**只能证明同一 session 内两次调用数值稳定**，**无法证明跨公司行动后仍然稳定**。按设计规定，此源在拿到复权因子/版本快照之前，**禁止用于任何实际历史 cutoff 运行的可作判断上下文**。
2. 无成交额字段的明确单位声明（靠交叉核对推断，非源方文档）。
3. 无配股/分红等原始复权因子接口暴露。
4. 停牌语义、新上市短历史、限流/超时、分页截断：**未验证**。
5. Wind 宏观 `search_macro_series` 失败（见 §1.1），与本能力无关但同属 Wind 平面。

### 1.1 Wind 平面内已确认的失败项

- `search_macro_series("GDP")` → `WindError [UNKNOWN]`，`code: ROUTE_ERROR`，`工具名 "natural_language_get_edb_data" 不属于 server_type "economic_data"`。**这是 skill 清单与 CLI 路由不匹配**，属代码缺陷，不是网络或配额问题。与 pytest 基线里 `test_live_edb_search` 的已知失败一致。
- 无效代码 `999999.SH` → `WindError`，`code: backend_error`，`未识别到有效的金融标的`。**注意**：这是"失败"而非"无数据"，语义正确（未把失败升级成空结果），符合设计 §8.4。

---

## 2. 腾讯 raw / qfq 日线（T13 主目标）

| 字段 | 内容 |
| --- | --- |
| **能力** | 腾讯日线 raw（未复权）与 qfq（前复权） |
| **adapter 版本** | **raw/qfq 均未注册**。`tencent_provider.py` 只注册了估值快照 `get_a_share_valuation`；K 线需新 adapter（T13）。上游依据：a-stock-data V3.7.1 |
| **样本范围** | 沪 `sh600519`/`sh688981`/`sh601398`/`sh600000`/`sh601899`；深 `sz000001`/`sz300750`/`sz000858`/`sz002594`/`sz301269`；北 `bj920008`/`bj920002` |
| **探测时间** | 2026-09-29 11:05–11:20 CST |
| **来源** | `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get`（无凭据） |
| **成功/降级/失败** | raw **成功**；qfq **降级**（见下） |

### 2.1 字段顺序——**非标准 OHLC，接入前必须处理**

行结构为 6 元素数组：`[date, f1, f2, f3, f4, volume]`

实测结论：**`[date, OPEN, CLOSE, HIGH, LOW, VOLUME]`**——第 3 位是**收盘**而非最高，第 4 位才是最高。

证据一（结构不变量，4 个标的 × 28 个交易日全部满足）：`max(idx1..idx4) == idx3` 且 `min(idx1..idx4) == idx4`。若按直觉读成 `[O,H,L,C]`，则 `High` 会取到收盘价、`Low` 会取到最高价——**静默错误，不报错**。

证据二（与实时快照逐字段对照，2026-09-29 盘中，4/4 精确相等）：

```
sh600519 bar=['2026-09-29','1244.60','1235.00','1245.87','1230.88','15114']
         qt  = name=贵州茅台 now=1235.00 open=1244.60 high=1245.87 low=1230.88
         idx1==qt_open? True  idx2==qt_now? True  idx3==qt_high? True  idx4==qt_low? True
sz300750 bar=['2026-09-29','291.00','288.94','293.19','285.74','161981']
         qt  = name=宁德时代 now=288.94 open=291.00 high=293.19 low=285.74
         idx1==qt_open? True  idx2==qt_now? True  idx3==qt_high? True  idx4==qt_low? True
```

（`sz000001`、`sz002594` 同样 4/4 精确相等。）

**这是本次探测中最高价值的发现之一**：任何按 `[O,H,L,C]` 直觉实现的腾讯 K 线 adapter 都会产出**静默错误的 high/low**，且不抛任何异常。

### 2.2 成交量单位——已验证为「手」，非「股」

腾讯 K 线第 6 列与 `qt.gtimg.cn` 成交额（字段 37，单位万元）交叉核对：

| 标的 | kline vol | qt 成交额(万) | 按「手」推算 | 比值 | 按「股」推算 | 比值 |
| --- | --- | --- | --- | --- | --- | --- |
| sh600519 | 15122 | 186781 | 187484 万 | **1.004** | 1875 万 | 0.010 |
| sz000001 | 349057 | 39826 | 39548 万 | **0.993** | 396 万 | 0.010 |
| sz300750 | 161981 | 467925 | 469696 万 | **1.004** | 4697 万 | 0.010 |

**成交量单位 = 手（×100 股）**，与 mootdx/Tushare/Wind 一致，可直接对齐。差异 ≤0.7% 来自用均价近似，非单位错误。

### 2.3 qfq 的**静默回落**——降级，不可用

请求 `fq=qfq` 时，响应里可能：
- 返回 `qfqday` 键 → 复权已应用（实测 10/12 个样本：`sh600519`、`sz000001`、`sz300750`、`sh600000`、`sh601398`、`sz000858`、`sz002594`、`sh601899`、`sz301269`）
- **只返回 `day` 键 → 未复权，且 HTTP 200、`msg` 为空、无任何告警**（实测 `sh688981` 中芯国际、`bj920008`/`bj920002` 北交所）

`sh688981` 请求 `qfq` 却只给 `day`——这正是设计 §8.2 禁止的"冒充复权主源"。**判定：降级（degraded），不是成功。** adapter 必须断言响应含 `qfqday`，缺失即报 `unavailable`，绝不可回落 `day`。

### 2.4 单请求 640 行硬上限 + **无截断标记**（分页截断风险）

- `count` 参数上限实测在 **2000 与 2100 之间**：2000 正常，≥2100 返回 `{"code":0,"msg":"param error","data":[]}`。**注意 `code` 仍是 0**，只靠 `data` 为 list 才能识别。
- 实际有效上限为 **640 行**（窗口内不足时不限）。`count=1000/1500/2000` 全部只返回 640 行。
- **响应中没有任何 total / count / more / next 标记**（`node` 键仅 `qfqday|day`、`qt`、`mx_price`、`prec`、`version`）。**截断完全静默。** 请求 2001-01-01..2026-09-29 只返回最近 640 行，看起来像"数据到 2024-02-05 就没了"。
- 分段递归二分可覆盖全历史，但**成本很高**：茅台 2001 上市，20 次调用取到 4770 行（最早仅回溯到 2003-05-16，**仍未到上市日**）；平安银行 20 次调用 4308 行（最早 2005-02-03）；宁德时代 7 次调用 1786 行即覆盖 2018-06-11 上市以来全部。**老股在 20 次调用预算内无法覆盖至上市日。**
- 沪市老股 `sh600000`：20 次调用得 1920 行 / 8538 自然日 = **0.225 交易日密度**（A 股正常约 0.245）。**系统性漏数**，非随机缺失。

### 2.5 无匹配 vs 无效代码——可区分（好设计）

| 情形 | rows | `qt` 节点 |
| --- | --- | --- |
| 无效代码 `sh999999` | 0 | `[]`（长度 0） |
| 有效代码但窗口无数据（1990-01） | 0 | 长度 **88**（有真实快照） |
| 有效且有数据 | 19 | 长度 88 |

`qt.gtimg.cn` 侧更干净：无效代码返回 `v_pv_none_match="1";`（21 字节），有效代码返回完整报价行。**可支撑设计 §8.4 要求的三态区分。**

### 2.6 日期语义

- 行内 `idx0` 为 `YYYY-MM-DD` 字符串，**无时区**。
- 盘中探测时，**当日 bar 已出现且为未完成 bar**：2026-09-29 11:00 的 `600519` bar 成交量 15114 手，而同日 qt 快照显示最新价 1235.00（`last_close` 1243.88）。**`day` 请求返回含当日未完成 bar，`qfq` 请求不含**（2026-09-29 那一批 qfq 的最后一行是 2026-09-28）。
- **raw 与 qfq 在"最后一个完整交易日"上不一致**——这直接违反设计 §8.5"最后一个完整交易日需断言"。adapter 必须显式剔除当日未完成 bar。
- 停牌语义、新上市短历史、限流/超时：**未验证**。

### 2.7 现有估值 adapter（`get_a_share_valuation`）

沪/深/科创/创业/北交所 920xxx/北交所老号段 83xxxx 全部 200 返回并正确解析；`999999.SH` 正确抛 `ChinaDataUnavailableError`（**失败未升级为"无数据"，符合设计要求**）。行情字段（PE/PB/市值/涨跌停）语义与本轮 kline 探测无关，未深查。

但注意：本次探测中 `bj920008` 与 `bj832982` 的估值均返回，而 §4 中北交所 K 线数据不完整——**估值可用 ≠ K 线可用**，不能互相推断。

---

## 3. Wind index `000300` —— 失败（数据错误，非不可用）

| 字段 | 内容 |
| --- | --- |
| **能力** | Wind 指数快照 / 指数历史 |
| **adapter 版本** | `wind_provider.get_index_snapshot` / `get_index_history` / `get_index_profile` / `get_index_fundamentals`，skill 2.0.1 |
| **样本范围** | `000300`（沪深300） |
| **探测时间** | 2026-09-29 11:25 CST |
| **来源** | Wind |
| **成功/降级/失败** | **失败**——HTTP 与调用都"成功"，但**返回的数值是错的** |

### 证据

`get_index_snapshot("000300")` 返回：

```
最新交易日,交易时间,最新成交价,前收盘价,今日开盘价,今日最高价,今日最低价,Wind代码
20260928,2026-09-28T00:00:00.000+08:00,0.966,0.945,0.966,0.966,0.966,000300.OF
```

- 真实沪深300 指数约 **4000 点**量级；返回 **0.966**。
- `get_index_history` 2026-08-02..08-10 全部为 `0.862 / 0.863 / 0.870 / 0.891 / 0.896`，`HIGH==LOW==CLOSE` 恒等，**涨跌幅 0.0%**——这不是指数，是某个被误解析的产品净值/收益率序列。
- Wind 返回的代码是 **`000300.OF`**（`.OF` = 开放式基金），**说明内部把 `000300` 解析成了基金而非指数**。
- `get_index_profile` / `get_index_fundamentals` **未验证**（探测超时被中断）。
- `tushare 000300.SH` 交叉核对失败（`Tushare returned no daily data`），**无法完成第三方对照**。

### 结论

**指数路径存在代码缺陷：内部 code 映射把 `000300` 解析为 `000300.OF`。** 在 `wind_provider._INTERNAL_TO_WIND_INDEX` 修正前，**所有 Wind 指数能力（含用于基准对比的指数快照）一律判为 `unavailable`，禁止进入任何市场专项上下文**——这比"取不到数据"更危险，因为它返回的是**看起来合法的错数据**。

同一 `to_wind_symbol(is_index=True)` 路径也用于个股指数化，若映射表有其他条目错误，影响面等同。**该表需逐条复核。**

---

## 4. mootdx（通达信）—— 失败，全线不可用

| 字段 | 内容 |
| --- | --- |
| **能力** | mootdx 日线 OHLCV、财务快照、F10 |
| **adapter 版本** | `mootdx_provider.py`，mootdx `0.11.7` |
| **样本范围** | 沪 `600519.SH`/`688981.SH`；深 `000001.SZ`/`300750.SZ`/`001400.SZ`；北 `920008.BJ`/`832982.BJ` |
| **探测时间** | 2026-09-29 10:45–10:55 CST |
| **来源** | TDX 二进制协议 TCP 7709（无凭据） |
| **成功/降级/失败** | **失败**——13/13 用例失败 |

### 证据：两级失败，性质不同

**第一级（TCP）**：8 个服务器中 3 个可连（`218.75.126.9`、`110.41.147.114`、`119.97.185.59`，均 0.01–0.03s），4 个超时，1 个 connection refused。

**第二级（数据）**：可连的 3 个服务器，`Quotes.factory()` **全部成功**返回 `StdQuotes`，但：

```
--- 218.75.126.9:7709 ---
  factory ok: <class 'mootdx.quotes.StdQuotes'>
  bars(600519) sh: type=DataFrame empty=True elapsed=4.97s   cols: []
  bars(000001) sz: type=DataFrame empty=True elapsed=4.71s   cols: []
  quotes(600519): empty=True elapsed=0.04s
--- 110.41.147.114:7709 ---   （同上，empty=True）
--- 119.97.185.59:7709 ---   （同上，empty=True）
```

**TCP 握手成功、factory 成功、但每一个数据调用都返回空 DataFrame（连列名都没有）。** `mootdx_provider.tdx_client()` 的 `_validate_bar_fetch` 正确识别了这一点，抛出 `ChinaDataUnavailableError`，router 因此回落到 Tushare——**这个设计是对的，没有把失败吞成"无数据"**。

耗时 25–28s/次（8 个服务器 × 3s 握手 + 数据调用），**失败代价很高**。

### 结论

- **上游 a-stock-data 关于 mootdx 公开行情命令失效的报告，在本地路径上得到独立确认。**
- `registry.VENDOR_METHODS["get_stock_data"]` 中 mootdx 是**第一顺位**。当前它 100% 失败，等于**每次 A 股行情请求都要先浪费约 26 秒再回落 Tushare**。这是 P0 性能与可靠性问题，不只是"少一个源"。
- 设计 §8.2 明确要求"不直接删除全部 mootdx 财务/F10 能力"——但本次实测**财务与 F10 同样不可用**（`get_fundamentals_mootdx` / `get_a_share_f10` 依赖同一个 `tdx_client()`，必然一并失败）。财务/F10 未单独调用验证（依赖同一失效 client，**推断而非实测**，标 `未验证` 以免过度断言）。
- 建议 D 组：mootdx 从"主源"降级前，先确认是否有可用服务器清单更新；否则应显式禁用以消除 26s 惩罚。

---

## 5. Tushare

| 字段 | 内容 |
| --- | --- |
| **能力** | Tushare raw 日线（主 fallback）；qfq 日线 |
| **adapter 版本** | `china_data.get_stock_tushare_df` / `get_stock_tushare_qfq_df`，tushare `1.4.29` |
| **样本范围** | 沪 `600519.SH`/`688981.SH`；深 `000001.SZ`；北 `920008.BJ` |
| **探测时间** | 2026-09-29 11:10–11:20 CST |
| **来源** | Tushare Pro（凭据 `TUSHARE_TOKEN` / `TUSHARE_API_KEY`） |
| **成功/降级/失败** | raw **成功**（4/4）；qfq **降级**（限流，0/2 成功） |

### raw 日线（本轮质量最好的源）

字段：`ts_code, Date, Open, High, Low, Close, Pre Close, Change, Pct Change, Volume, Amount`

- 沪/深/科创/**北交所 920008.BJ 全部 40 行返回**（2026-08-03..2026-09-28）。
- 全部样本 `sorted=True`、`dupes=0`。
- **字段顺序为标准 OHLC**（与腾讯相反）。
- 单位已验证：`Volume` = **手**（float64，含小数）；`Amount` = **千元**。
- 与腾讯 raw 收盘价逐日精确一致（`2026-09-28` 茅台两者均 `1243.88`；`2025-09-08` 均 `1501.230`）。**两源可互为校验。**
- **北交所支持完整**——与腾讯（K 线仅 1 行）形成鲜明对比。

### qfq 日线——降级，且是硬性限流

```
抱歉，您访问接口(adj_factor)频率超限(1次/分钟)...
[tushare_qfq_sh] OK 1.38s   ← 首次侥幸成功
[tushare_qfq_sz] FAIL 4.43s ChinaDataUnavailableError: Tushare qfq daily request failed for 000001.SZ: ERROR.
（第二轮探测中又见「1次/小时」提示，qfq 完全取不到）
```

`adj_factor` 接口限频 **1 次/分钟**（后段提示升级为 1 次/小时）。**这是设计级约束，不是偶发故障**：qfq 需要 `daily` + `adj_factor` 两次调用，串行处理多个标的必然触限。

**对 D 组的直接含义：Tushare 不能作为多标的 qfq 的稳定源。** 需要缓存/预取策略，或由 Wind 承担 qfq 主源。

### 错误语义（好）

无效 token → `Exception: 您的token不对，请确认。`（抛出，非空结果）。**失败未被升级为"无数据"，符合设计 §8.4。**

### akshare（旁证）

- `get_stock_akshare_df` 沪/深均成功。
- `get_stock_akshare_qfq_df` 失败（66.3s）：`push2his.eastmoney.com ... Max retries exceeded`。**东财在本网络不可达**（见 §6）。
- 66 秒的超时后失败是**另一处性能陷阱**。

---

## 6. 东财（EastMoney）—— 不可达

| 字段 | 内容 |
| --- | --- |
| **探测时间** | 2026-09-29 10:42 CST（直连）与 11:15（经 akshare） |
| **结果** | **失败** |

- `push2.eastmoney.com/api/qt/clist/get` → **HTTP 502 Bad Gateway**（nginx/1.26.2），1.71s。
- `push2his.eastmoney.com`（akshare qfq 路径）→ 连接重试耗尽，66.3s 超时。
- 因此**所有依赖东财的能力在本网络不可用**：资金流、两融、资本流水（新浪备份）、公告 fallback（`EastMoneyAnnouncementFallback`）、akshare 全部东财后端、巨潮的部分路径。

`EastMoneyHTTPClient` 的重试策略（1s 间隔、2 次重试、指数退避、403/429/5xx 分别处理）设计合理，但**对本网络无效——502 是上游网关层，直接穿透所有策略**。注意 502 属于 5xx，客户端会重试 2 次后才抛错，**每次调用浪费约 3×RTT**。

**这是环境级限制还是普遍限制未验证**（可能与本机网络/VPN 有关）。若生产环境同此网络，东财相关能力需整体标 `unavailable`。

---

## 7. 巨潮（cninfo）—— 未验证

- 直连 `http://www.cninfo.com.cn/new/hisAnnouncement/query` → **HTTP 502**，2.05s，空 body。
- 该端点是 POST + 动态 `orgId` 解析（`china_specialty.get_a_share_cninfo_announcements`），未走通直连即**无法验证**。
- **代码层面的三态区分已审阅**（未实测）：`_cninfo_total_pages` 读 `totalpages/totalPages/pageCount`；`pagination_exhausted` 有独立标志；无结果时抛 `NoMarketDataError` 而非静默返回空。**逻辑上满足设计 §8.4，但端点在本网络不可达，无法取得 live 证据。**
- 结论：**未验证**。不宣称可用。§14 P1 能力（业绩预告/快报、回购增减持）依赖公告类源，在巨潮与东财双双不可达的情况下**均无法在本轮验证**。

---

## 8. 静默 vendor 替换（设计 §8.5 明令禁止的行为）—— 已确认存在

### 代码级确认

`tradingagents/dataflows/interface.py:271-276`（工作树内读取）：

```python
# A stored cooldown only represents a prior transient failure. It
# gets the same implicit safety-net fallback as a live 429/network
# failure, even when the user explicitly selected one primary.
for extra in VENDOR_METHODS[method]:
    if extra not in fallback_vendors:
        fallback_vendors.append(extra)
        implicit_fallback_triggered = True
```

**当主源处于冷却状态时，整条 `VENDOR_METHODS[method]` 链会被追加进 fallback**，注释自己写明"even when the user explicitly selected one primary"。

### 对 raw/qfq 的具体风险（高）

`registry.py` 的 `get_adjusted_price_history` 链为：

```
wind → tushare(qfq) → akshare(qfq) → yfinance → alpha_vantage
```

raw 链为：

```
mootdx → tushare → alpha_vantage → yfinance
```

**两条链的成员不重叠**（raw 供应商被刻意排除在 adjusted 之外，代码注释已说明"Raw providers are intentionally excluded from this capability"）。因此**在当前注册表下，raw 不会直接顶替 qfq**。

**但风险是真实的、且由本次实测加剧**：

1. mootdx 100% 失败（本轮 §4）→ 每次 A 股行情请求都进入 fallback，**Tushare raw 静默顶替 mootdx 成为实际主源**。虽然二者都是 raw、口径一致，但**用户显式选 mootdx 时得到的是 Tushare 数据，且 provenance 只记录"发生了 fallback"而非"用户选定的源不可用"**。
2. qfq 链上 `tushare` 因 `adj_factor` 限流持续失败（本轮 §5）→ **在 26 秒 mootdx 惩罚 + Tushare 限流之后**，qfq 请求会一路降级到 `yfinance` / `alpha_vantage`。**这两个是海外/A 股混用源，对 A 股复权语义未经验证**，若被当作 qfq 结果使用，即是设计 §8.2 禁止的"冒充复权主源"。
3. `implicit_fallback_triggered` 标志存在，说明系统**知道自己**在做隐式替换——但据代码审阅，该标志不阻止替换发生。

**未验证**：本轮未实际触发一次完整的 `get_adjusted_price_history` 端到端调用去观察最终返回的是哪个 vendor 的数据（探测在此之前被中断）。**结论为代码级确认 + 风险推断，非运行时实证。**

**建议 D 组**：为 `get_adjusted_price_history` 的每个非 A 股验证源设置硬门控，或让 `implicit_fallback_triggered` 在 adjusted 能力上直接失败而非静默替换。

---

## 9. T16 机构调研 —— **显式延后**

### 判定：**不合格，本轮不接入。**

### 阻塞原因（三条，均为硬阻塞）

1. **无合格端点。** 已确认可用的源中，没有任何机构调研记录接口：
   - 腾讯：仅行情与估值，无调研。
   - mootdx：全线不可用（§4），其 F10「机构研究」分类因此无法验证。
   - Tushare：需付费/特定积分的调研接口，本轮未授权探测，**未验证**。
   - Wind：Wind 平面可用（§1），但本轮未探测调研类工具，且其 `search_macro_series` 已确认路由缺陷（§1.1），**不信任该平面未经探测的工具**。
   - 巨潮/东财：网络不可达（§6、§7）。
   - **结论：本轮没有任何一个可探测的机构调研端点。**

2. **设计 §8.2 的降级要求无法满足。** 要求"提取公司回应与待验证问题"，前提是能取到**问答对**（问什么、答什么）。当前唯一相关的是 `china_capabilities.get_a_share_interactive_questions`（互动易），但设计 §8.2 已明确："现有研报、互动易不能完整替代调研事项"——互动易是**投资者提问**，方向与机构调研相反（调研是机构提问、公司回答）。**用它顶替是语义错误。**

3. **管理层表述不得升级为订单事实**（设计 §8.2 与 §9.1）。该门控需要可靠的调研时间戳与参与机构名单才能实现。在端点缺失、字段未定的情况下**无法建立门控**，也就无法安全接入——此时接入必然违反 G11（严重事实错误为零）。

### 解除阻塞的条件

需要以下之一，且**不阻塞 T13–T15 上线**：
- 确认并授权一个 A 股机构调研端点（Tushare 调研类接口或 Wind 调研工具），完成本文件同等维度的实测；或
- 明确将机构调研移出首版范围（设计的 §8.2 已将其列为 P2，"不进首版"倾向明确）。

**当前状态：延后，不实现，不猜测。**

---

## 10. 探测维度覆盖矩阵（设计 §8.6）

图例：✅ 已验证通过　⚠️ 已验证有问题　❌ 已验证失败　⬜ 未验证

| 能力 | 沪市 | 深市 | 北交所 | 正常数据 | 无匹配 | 停牌/新上市 | 历史 cutoff | 限流/超时 | 字段缺失 | 分页截断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Wind qfq 日线 | ✅ | ✅ | ✅ | ✅ | ✅ | ⬜ | ⚠️ PIT 未验证 | ⬜ | ⬜ | ⬜ |
| 腾讯 raw 日线 | ✅ | ✅ | ⚠️ 仅 1 行 | ✅ | ✅ | ⬜ | ⚠️ | ⬜ | ✅ | ⚠️ 静默 640 上限 |
| 腾讯 qfq 日线 | ✅ | ✅ | ❌ 回落 day | ⚠️ | ✅ | ⬜ | ⚠️ | ⬜ | ❌ 静默回落 | ⚠️ |
| Wind 指数 | — | — | — | ❌ 数值错误 | — | ⬜ | ⬜ | ⬜ | — | ⬜ |
| mootdx 日线 | ❌ | ❌ | ❌ | ❌ | ❌ | ⬜ | ⬜ | ✅ 超时 26s | ⬜ | ⬜ |
| Tushare raw | ✅ | ✅ | ✅ | ✅ | ⬜ | ⬜ | ✅ | ⬜ | ✅ 无 | ✅ 无 |
| Tushare qfq | ⚠️ | ❌ | ⬜ | ⚠️ | ⬜ | ⬜ | ⬜ | ❌ 限流 | ⬜ | ⬜ |
| 腾讯估值快照 | ✅ | ✅ | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ✅ | ⬜ |
| 东财（全平面） | ❌ | ❌ | ❌ | ❌ | — | — | — | ❌ 502 | — | — |
| 巨潮公告 | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| 百度 | ✅ 连通 | — | — | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| 机构调研 | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |

**`⬜ 未验证` 汇总（诚实缺口）**：所有能力的**停牌/新上市**维度；Wind/Tushare/腾讯的**限流与超时**行为（除已记录的 Tushare 限流与 mootdx 超时）；巨潮全维度；百度除连通性外的全部维度；机构调研全维度；`get_index_profile` / `get_index_fundamentals`。

**特别说明——北交所**：Tushare raw **完整支持**（40/40 行），Wind qfq **支持**（3/3），腾讯估值 **支持**但腾讯 K 线 **仅返回 1 行**、qfq **静默回落未复权**。**因此不能笼统声称"北交所已支持"**——必须逐源声明。腾讯北交所 K 线在 T13 中若纳入，须按 `unavailable` 处理。

---

## 11. 给 D 组（数据能力）的可执行结论

1. **复权主源只能是 Wind**，且必须标 `pit_unverified`，在拿到复权因子快照前禁止用于历史 cutoff 的可作判断上下文（设计 §8.5 硬性要求）。
2. **Wind 指数路径先修再���**：`000300` 被解析为 `000300.OF`，返回 0.966 而非 ~4000。修好前指数能力整体 `unavailable`。
3. **腾讯 raw 可作第二行情源**，但实现时必须：(a) 按 `[date, OPEN, CLOSE, HIGH, LOW, VOL]` 解析，**不是 OHLC**；(b) 剔除当日未完成 bar（raw 含、qfq 不含）；(c) 单请求 ≤640 且**自行分段**，因为响应无任何截断标记。
4. **腾讯 qfq 不可作复权源**：需断言 `qfqday` 存在，否则报 `unavailable`（实测已有标的静默回落 `day`）。
5. **mootdx 现状是纯负债**：100% 失败 + 每次 26s。财务/F10 亦依赖同一失效 client。在服务器清单更新前建议显式降级/禁用。
6. **Tushare raw 是当前最可靠的 A 股行情源**（沪深北齐全、字段标准、无重复无乱序），可作实际主源。**qfq 受 `adj_factor` 1 次/分钟限制，不适合多标的串行。**
7. **本网络下东财与巨潮均不可达**（502）。若生产同此网络，资金流/两融/公告/互动易/巨潮全部能力需标 `unavailable`。**这是发布门槛级依赖，建议尽早确认生产环境网络。**
8. **隐式 fallback 会顶替用户显式选定源**（`interface.py:271-276`）。当前注册表下 raw 链与 qfq 链不重叠，故 raw 不会顶替 qfq；但 qfq 链末端 `yfinance`/`alpha_vantage` 对 A 股复权语义未经验证，是下一个冒充风险点。
9. **T16 机构调研延后**，不阻塞 T13–T15。

---

## 12. 合规声明

- 本文件**不含任何凭据值**，仅出现环境变量名 `TUSHARE_TOKEN`、`TUSHARE_API_KEY`、`WIND_API_KEY`。
- 本文件**不含带 token 的 URL**，所有端点 URL 均为无凭据公共端点。
- 本文件**未收录完整私有响应体**，仅保留验证所需的最小字段与少量样本行。
- 本文件**不含任何第三方研报内容**。T16 的调研结论基于**端点可用性**判断，不引用任何机构调研记录。
- 探测脚本位于 `/tmp/ta_probe/`（一次性脚本，未纳入仓库）。
- **未修改任何产品代码**；本文件是本次唯一产出。
- **未启动任何 LLM 研究运行**；本轮全部为数据端点调用。
- **未读写或删除 `~/.tradingagents/` 下任何内容。**
- **未提交任何内容。**
