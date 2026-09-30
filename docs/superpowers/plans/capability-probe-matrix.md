# T04 能力探测矩阵（标准定义）

- **本文件只定义标准与判定规则，不含实测结果。** 实测由 H agent 执行，产出 `docs/superpowers/operations/capability-probe-2026-09-29.md`。
- 依据：设计 §8.6「实施前端点探测清单」。
- 候选能力清单来自 `tradingagents/dataflows/registry.py:334` 的 `VENDOR_METHODS`（实测 **61 个 method / 23 个 vendor**）。

## 1. 判定三态（唯一合法取值）

每项能力 × 每个维度必须落在且只落在以下三态之一。**禁止「应该可用」「基本可用」「正常」这类不可判定表述。**

| 态 | 定义 | 判据（全部满足） | 禁止行为 |
| --- | --- | --- | --- |
| **成功** | 返回了完整、可用、口径可验证的数据 | ① HTTP/调用成功；② 响应字段完整（无必需字段缺失）；③ 日期/单位/时区通过校验；④ provenance 完整（vendor、时间、样本范围） | 缺字段却标成功 |
| **降级** | 有数据但**可信度或完整性受损**，可继续但必须标注限制 | ① 有返回；② 但触发下列任一：分页截断、字段缺失、覆盖窗口不完整、单位存疑、走了 fallback 链、时点未验证 | 把降级写成成功；把降级写成「无数据」 |
| **失败** | 无数据，或结果不可用 | ① 供应商错误/限流/超时；② 鉴权失败；③ 返回空且**无法证明「完整覆盖且无匹配」** | **把失败写成「无事件」或「无匹配」** |

### 1.1 第四态：未验证（合法，但只用于本轮未探测项）

| 态 | 定义 | 使用条件 |
| --- | --- | --- |
| **未验证** | 本轮没有执行探测，或无权限/无凭据 | 端点需要本轮不提供的凭据；时间不足；H agent 未覆盖 |

**「未验证」≠「失败」，也 ≠「成功」。** 设计的 G13 门槛明确：「未验证不能算通过」。

## 2. 八个必测维度（每项能力均须覆盖）

| ID | 维度 | 沪市样本 | 深市样本 | 通过判据 |
| --- | --- | --- | --- | --- |
| **D1** | 正常数据 | `600580.SS` | `002335.SZ` | 字段完整、日期连续、值合理 |
| **D2** | 无匹配 | 构造不存在的代码（如 `600999.SS` 当日） | `002999.SZ` | 返回**空**，且能证明「完整覆盖窗口且无匹配」；不能是超时伪装成空 |
| **D3** | 停牌 / 新上市 | 需 H agent 现场确认当日状态的样本 | 同左 | 停牌日无 bar 且可归因为官方停牌；新上市不足窗口时如实返回短历史，**不补齐** |
| **D4** | 历史 cutoff | 请求 ≤2026-09-08 的数据 | 同左 | 返回的每条记录日期 ≤ cutoff；**不得混入 cutoff 之后的数据** |
| **D5** | 限流 / 超时 | 触发 429 或超时 | 同左 | 归类为 `rate_limited` / `timeout`，**不得**归类为「无数据」 |
| **D6** | 字段缺失 | 请求返回部分字段缺失的记录 | 同左 | 明确列出缺失字段名；必需字段缺失 → **降级或失败**，不静默填 null |
| **D7** | 分页截断 | 触发分页上限 | 同左 | 标记 `truncated=true` 且给出已取/总数；**不得声称覆盖完整** |
| **D8** | 单位与口径 | 成交量单位、复权口径、货币单位 | 同左 | 有明确断言：成交量是股还是手、是否复权、金额单位 |

### 2.1 北交所（BJ）—— 精确声明，不假设

> 设计 §8.6：「北交所若声明支持则补同等测试；**否则精确标不支持，不能假设通用代码自动可用**。」

规则：

1. H agent 必须**显式判定**每项能力对 `.BJ` 后缀的行为；
2. 判定为支持 → 补齐 D1–D8 全维度（沪/深/北三市）；
3. 判定为不支持 → 在报告中写 **`unsupported`（精确不支持）**，并注明代码中是否存在会误匹配的通用分支；
4. **禁止**留空、禁止写「未知」后按支持推进、禁止用沪/深结果代替。

**当前状态：`unknown`。** A agent 不执行探测（探测归 H agent）。本轮无任何 `.BJ` 实测数据。

## 3. 能力清单（12 项候选 × 8 维度 = 96 格）

选取依据：设计 §8.2 的 P0/P1/P2 优先级 + `VENDOR_METHODS` 实测注册表。

| ID | 能力 | registry method | 设计优先级 | 当前 fallback 链长 | 备注 |
| --- | --- | --- | --- | ---: | --- |
| **A1** | 普通日线（raw） | `get_stock_data` | P0 | 4 | mootdx → tushare → alpha_vantage → yfinance |
| **A2** | 复权日线（qfq） | `get_adjusted_price_history` | P0 | **5** | wind → tushare → akshare → yfinance → alpha_vantage |
| **A3** | 估值快照 | `get_a_share_valuation` | P0 | 1 | tencent 单一 vendor |
| **A4** | 财务报表 | `get_income_statement` / `get_balance_sheet` / `get_cashflow` | P0（必需能力） | 4 | tushare → sina → alpha_vantage → yfinance |
| **A5** | A 股公告（巨潮） | `get_a_share_cninfo_announcements` | P1 | 2 | cninfo → china_exchange |
| **A6** | A 股公告（交易所） | `get_a_share_exchange_announcements` | P1 | 1 | china_exchange |
| **A7** | 公司新闻 | `get_news` | P1 | **7** | tavily → doubao → bocha → eastmoney → … |
| **A8** | EPS 一致预期 | `get_a_share_eps_forecast` | P1（可选） | 1 | ths |
| **A9** | 内部人交易 | `get_a_share_insider_trades` | P1 | 1 | eastmoney（T15 的对照基线） |
| **A10** | 机构研报 | `get_a_share_research_reports` | P2 | 1 | eastmoney |
| **A11** | 互动易问答 | `get_a_share_interactive_questions` / `_answers` | P2 | 1 | akshare |
| **A12** | 财联社电报 | `get_cls_telegraph` | 后续 | 1 | cls |

### 3.1 设计 §8.2 点名但**尚无对应 method** 的能力

| 设计要求 | registry 现状 | 状态 |
| --- | --- | --- |
| 腾讯**日线/K 线**（raw 与 qfq 各一） | `get_a_share_valuation` 只覆盖**估值快照**；`get_stock_data` 链中**无 tencent** | **未注册 —— T13 必须新建** |
| 业绩预告 / 快报事件 | 无独立 method | **未注册 —— T14** |
| 回购 / 增减持**执行链** | 仅有 `get_a_share_insider_trades`（静态快照，非执行链） | **未注册 —— T15** |
| 机构调研记录 | 无独立 method | **未注册 —— T16（可显式延后）** |

**这 4 项是 H agent 探测清单的重点**，也是 G13「新源可用」门槛的主要风险点。

## 4. 探测记录必填字段

每条记录必须包含（缺任何一项 → 该格记「未验证」）：

| 字段 | 说明 | 反例（禁止） |
| --- | --- | --- |
| `capability` | 能力 ID（A1–A12） | — |
| `dimension` | 维度 ID（D1–D8） | — |
| `state` | **成功 / 降级 / 失败 / unsupported / 未验证** | 「正常」「可用」「OK」 |
| `adapter_version` | adapter 代码版本（commit sha + 文件） | 「最新」 |
| `sample_scope` | 样本范围（代码、日期区间、条数） | 「部分股票」 |
| `probe_time` | 探测时间（含时区） | 「今天」 |
| `source` | 实际命中的 vendor（**不是首选，是实际**） | 「tushare」（实际走的可能是 sina） |
| `fallback_triggered` | 是否触发 fallback；触发原因 | 省略 |
| `response_field_summary` | 响应字段名清单（**不含完整私有响应**） | 贴原始 JSON |
| `date_unit_verification` | 日期/单位如何验证、结论 | 「看起来对」 |
| `limitations` | 已知限制 | 省略 |
| `pit_status` | 时点验证状态：`verified` / `pit_unverified` | 省略 |

### 4.1 报告禁止内容

- ❌ 任何凭据、token、带 token 的 URL
- ❌ 完整私有响应原文
- ❌ 无权分发的研报全文
- ❌ 「应该可用」「预期可用」

**Fixture 仅保留可合法保存的最小字段，或明确标注的合成样例。**

## 5. 与设计 §9.1 质量矩阵的衔接

探测结论直接决定 case 完成程度与研究优先级上限：

| 探测结果 | 允许的 case 完成程度 | 允许的优先级 |
| --- | --- | --- |
| A1/A3/A4/A5 任一 **失败或未验证** | `partial` / LOW_CONFIDENCE | 仅「信息不足」 |
| A2（qfq）**未验证或 pit_unverified** | 价格数据**不得进入市场专项判断上下文**；`partial` | 仅「信息不足」 |
| A5/A6 **分页截断（D7）** | 事件覆盖 `coverage_unknown` | 仅「信息不足」 |
| A5/A6 **失败（D5/D2）** | 记 `unavailable`，**禁止写「无事件」** | 仅「信息不足」 |
| 全部必需能力成功且无未处理限制 | `complete` / PASS | 四类均可 |

**关键区分（设计 §9.1 末段）**：`not_applicable`（未披露/行业不适用）、`unavailable`（供应商取不到应有数据）、`pit_unverified`（时点无法证明）—— **三者不得混用**。

## 6. H agent 交付判据

`docs/superpowers/operations/capability-probe-2026-09-29.md` 通过条件：

- [ ] 12 项能力 × 8 维度 = 96 格，每格有明确 `state`（含 `未验证`，不留空）
- [ ] 每格含 §4 全部 12 个必填字段
- [ ] `.BJ` 支持性有精确结论（支持 → 三市全测；不支持 → 写 `unsupported`）
- [ ] raw 与 qfq **分别**有结论，未混拼
- [ ] 无凭据、无带 token URL、无完整私有响应
- [ ] 无权限的端点标「未验证」而非「可用」
- [ ] 与 §5 质量矩阵的对应关系明确

## 7. 验收自查（T04 = 标准侧）

- [x] ≥10 项候选能力（**12 项**）× ≥8 个维度矩阵（**D1–D8**）
- [x] 每项有成功/降级/失败三态定义（§1）+ unsupported + 未验证
- [x] 明确写出「北交所未声明支持则精确标不支持」（§2.1）
- [x] 记录字段清单（§4，12 项）
- [x] 与设计 §9.1 质量上限的衔接（§5）
- [x] 未执行任何 live 探测（归 H agent）；本文件全部为标准与静态代码事实
- [x] 无凭据、无 token、无带凭据 URL
