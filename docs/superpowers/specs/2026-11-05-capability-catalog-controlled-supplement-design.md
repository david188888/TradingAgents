# 数据能力目录与受控补证工具层

日期：2026-11-05。Status: Approved design; Tasks 1–6 implemented and live acceptance verified on 2026-11-05; §13 keeps each decision's writing-time state.

Treat §1–§12 as designed intent and §13 as the dated implementation record; verify current behavior in code and the current-state docs.

依据：本会话确认的方向——保留 V9 Insight 证据护栏与专项独立；不退回上游 Bull/Bear；智能化优先走「LLM + 受控 tool calling + 上下文管理」，而非开放式多 Agent。消费点定为：**程序预取最小证据包；专项仅在显式缺口时按能力目录补证**。

相关现行文档：

- [ARCHITECTURE.md](../../../ARCHITECTURE.md)
- [A-share data capabilities](../../operations/a-share-data-capabilities.md)
- [双路检索设计（历史冻结）](2026-10-23-dual-search-research-design.md)
- [Insight 协议](../../plans/2026-10-28-insight-protocol-design.md)

## 1. 问题与目标

### 1.1 问题

当前 V9 专项本质上是「角色 system task + 冻结 catalog + structured JSON」的固定 workflow。程序预取与双路搜索已提供大量材料，但：

1. 模型几乎不能按研究缺口选择**结构化数据工具**（Wind / a-stock-data 等）；补证出口主要是网页向的 `search_requests`。
2. 若把供应商全文或数十个端点说明塞进 prompt，token 成本高，且模型仍可能选错或误用。
3. 上游 TauricResearch 的 Bull/Bear 对立辩论会诱使「为立场硬找证据」；本 fork 已退役该路径，新设计不得回潮。

### 1.2 目标

1. 提供面向模型的短**数据能力目录**（约 12 张能力卡），说明数据在哪一类能力、解决什么、何时不该用。
2. 由程序侧 **Tool Gateway** 执行调用、路由后端、资格校验并写回冻结证据。
3. 专项仅在显式缺口时受控补证（每专项最多 1～2 次）；挑战 / 回应 / 综合第一版不开放写工具。
4. 保持：程序算数与引用校验、专项互不读草稿、综合只消费已保存 Insight、允许证据不足与 Hold/不确定。

### 1.3 非目标（v1）

- 完整 NVIDIA Auto Ontology / 企业图谱 / NL→SQL 产品化。
- 模型自选供应商、自拼底层 endpoint 或 Wind CLI 原始帮助全文入 prompt。
- 开放式研究 agent（自行决定阶段顺序、跳过维度、无限迭代）。
- 恢复 Bull/Bear 或交易信号目标函数。
- 一次暴露 a-stock-data 全部端点。
- 本设计不修改 Reader 投影语义，不迁移历史 run。

## 2. 方案选择

| 方案 | 含义 | 结论 |
| --- | --- | --- |
| A. 受控工具调用 workflow | 阶段固定；缺口处按目录选工具 | **采用为底座** |
| B. 专项内轻量 agentic 循环 | 专项内 N 轮观察→工具→再写 | **仅开在补证口**，N≤2 |
| C. 开放研究 agent | 模型编排整条研究 | 拒绝 |

推荐形态：**最小证据预取 + 能力目录驱动的受控补证**；B 的迭代只用于「声明缺口 → 调工具 → 写/修订 Insight」，不用于自由探索。

## 3. 总体流程

```text
程序：最小证据包预取 → 资格校验 → 冻结 catalog
专项 main：
  输入 = 本角色 catalog + 本角色可见的能力目录子集
  输出 = Insights 和/或 capability_requests[]
若有合法 capability_requests：
  程序 Gateway 执行 → 冻结增量证据 → 回灌本角色视图
  同专项至多再 1 次模型调用（supplement）写/修订 Insight
挑战 / 回应 / 综合：只读；不接受新的写工具请求（v1）
```

与现有双路补搜的关系：

- `news_search` 成为目录中的一种能力；DeepSeek / Tavily 仍由程序双路协调，模型不直接选家。
- 现有 `search_requests: string[]` 升级为（或并存一期后替换为）结构化 `capability_requests`。
- 网页补搜预算与结构化能力预算分账，避免一种耗尽误伤另一种；具体数字在实现计划中对照现行 `search_budget` / `BudgetBucket` 冻结进 run identity。

## 4. 能力目录（Capability Catalog）

### 4.1 载体

- 仓库内一份机器可读清单（建议 `tradingagents/dataflows/capability_catalog.yaml` 或等价模块常量 + 测试夹具）。
- 程序加载后生成两类视图：
  - **完整卡**：供 Gateway、审计、文档。
  - **压缩卡**：供模型 prompt（每卡约 50–80 字）。

目录内容冻结进 checkpoint identity 的摘要（例如 catalog schema version + 启用 capability_id 集合的 digest），避免恢复时能力集漂移。

### 4.2 能力卡字段

| 字段 | 用途 |
| --- | --- |
| `id` | 稳定 ID；模型只许引用此 ID |
| `title` | 短标题 |
| `solves` | 可回答的问题类型 |
| `not_for` | 明确禁止的用途（反「硬找证据」） |
| `inputs` | `query` 的含义；ticker 不是模型参数 |
| `returns` | 返回语义（序列/摘录/表格），不含投资结论 |
| `backends` | 程序路由候选；**不进入模型压缩卡** |
| `cost` | low / medium / high |
| `max_calls_per_run` | 单 run 上限 |
| `roles` | 哪些专项可见（operating / event / market） |
| `requires` | 如 `wind_credentials`；不满足则目录中不出现 |
| `prefetch_only` | true 时模型不可请求（仅文档化预取能力） |

### 4.3 v1 建议收录（约 12 张）

按研究问题聚类，不按供应商聚类：

| id | 主要服务对象 | 备注 |
| --- | --- | --- |
| `financials_detail` | operating | 核心三表已在预取时，本卡只补细项 |
| `valuation_history` | operating / market | |
| `disclosure_search` | operating / event | CNINFO 等官方披露 |
| `news_search` | event / operating / market | 封装现有双路搜索 |
| `ir_qa` | event / operating | 互动易 / e 互动 |
| `northbound_flow` | market | |
| `longhubang` | market / event | |
| `shareholder_count` | operating | |
| `holder_change` | operating / event | 增减持 / 回购 |
| `consensus_eps` | operating | |
| `industry_peers` | operating / market | |
| `wind_enrich` | 按角色子集 | 无 Wind 凭证时整卡隐藏 |

预取保留且标 `prefetch_only` 的能力（身份、日历、复权价、核心三表、基础估值快照）写在目录全文中供人读，**不**出现在模型可请求列表。

实现期可增减单卡，但不得在无设计修订的情况下把「可见可请求集合」扩到供应商全量端点。

## 5. Tool Gateway

### 5.1 模型请求形状

```json
{
  "capability_requests": [
    {
      "capability_id": "shareholder_count",
      "query": "",
      "gap_reason": "需核实近一年股东户数是否快速上升"
    }
  ]
}
```

规则：

1. `capability_id` 必须在本角色当前可见集合内。
2. `gap_reason` 必填，且应能对应本阶段 `unknowns` / limitations / 缺失字段；宿主可做轻量校验（非空、长度上限），不做主观「理由是否聪明」评判。
3. 单次模型输出请求条数有上限（建议 ≤2）；超出截断并记 gap。
4. 模型不得传后端名、API path、密钥或自由 SQL/CLI。
5. 请求只有 `capability_id` / `query` / `gap_reason` 三个固定字段：provider strict 结构化输出不接受自由键值对象。
   ticker 由宿主注入，模型不能指定其他公司；不需要参数的卡 `query` 填空字符串。
   未来某卡需要多个参数时，再扩字段或改为按 `capability_id` 区分的 union。

### 5.2 程序执行

1. 鉴权与 `requires` 检查；失败 → typed unavailable，不重试伪装成功。
2. 按卡内 `backends` 路由；记录 provider 级 provenance，不把密钥写入 run 产物。
3. 走现有 evidence / coverage 资格路径；空结果、失败、不支持必须区分。
4. 合格材料写入不可变增量并更新本角色可消费视图；编号（E/N）由程序分配。
5. 审计：capability_id、args 摘要、gap_reason、结果状态、耗时、预算扣减。

Gateway 属于 `dataflows/` + `execution/` 协作：适配与规范化在 dataflows；预算、调度、与 insight 阶段衔接在 execution。Graph 内核保持注入式，不直连 HTTP SDK。

## 6. 与 Insight 阶段的接缝

| 阶段 | 写工具 | 说明 |
| --- | --- | --- |
| 专项 main | 可 | 输出 Insights 和/或 capability_requests |
| 专项 supplement_k | 默认可再请求缺口，但计入同一专项 1～2 次总上限 | k∈{1,2}；与现行 `supplement_*` phase 对齐 |
| challenge | 否 | 避免辩论驱动翻证据 |
| response_* | 否（v1） | 回应基于已保存材料；缺口记入 limitations |
| synthesis | 否 | 只综合已保存 Insight |
| focus_response | 否（v1） | 不改变基线 |

专项独立性：补证回灌不得泄露其他专项草稿或未授权事实视图。

替换策略：

- 一期可并存：旧 `search_requests` 映射为 `news_search` 的兼容入口。
- 二期专项目录请求统一为 `capability_requests`；文档与契约同步。

## 7. 预算、身份与失败语义

1. 结构化能力调用与网页搜索分桶计数；耗尽时拒绝新派发并记录原因。
2. 取消、全局 deadline、checkpoint 冲突、疑似凭证问题不得伪装成「资料不足」。
3. 工具失败 ≠ 事件未发生；分析中必须保持 typed gap。
4. 补证后的 Insight 仍经 `compile_insights` / 引用与数值校验；未入证材料不得变成可采纳依据。
5. 有效配置中的目录版本、启用能力集、每专项补证上限冻结进 run identity；resume 时不一致则冲突拒绝。

具体数值（每专项次数、全 run 总次数、与现行 双路 50/50 等如何并列）在实现计划中对照代码冻结，不在本文写死未核对的数字。

## 8. Token 与上下文原则

本设计同时服务「智能化」与「降 token」：

1. 模型只看**压缩能力卡子集** + **当前角色需要的 catalog**，不看后端文档。
2. 预取倾向最小必要集；扩展项改为缺口驱动，减少无关大包重复塞入。
3. 工具返回先资格化再入证；入 prompt 的是受控摘录/结构化事实，不是原始供应商倾倒。
4. 目录本身禁止膨胀：新增能力卡要过「是否高频缺口、是否有程序包装、是否有 not_for」审查。

量化验证留待实现后用既有/扩展的 stage-input 测量（参见历史上 F04 只读测量思路）对比前后，不在无数据时承诺百分比。

## 9. 反模式（明确禁止）

1. 为支持当前 claim 而发起与 `gap_reason` 无关的取证。
2. 挑战阶段为「辩赢」新开工具。
3. 将 Bull/Bear 角色或强制对立重新引入补证环。
4. 模型输出投资指令、仓位或把工具原始数字当已渲染 N 引用绕过宿主。
5. 无凭证时仍展示 `wind_enrich` 诱使空调。

## 9.1 Task 3 实现决议（2026-11-05）

1. `news_search` 不经 Capability Gateway 执行：专项若请求该卡，Gateway 拒绝并提示走现有 `search_requests` / 双路补搜队列，网页预算仍走 DeepSeek/Tavily 桶。
2. `disclosure_search` v1 只返回公告目录的标题、日期与链接（可带类型），标注为目录摘录；不下载 PDF 正文。
3. 结构化卡优先复用仓库内 a-stock-data 同源适配：`get_a_share_cninfo_announcements`、`get_a_share_shareholder_counts_em`、`get_a_share_sse_e_interaction`；深市互动易按 a-stock-data §10.1 新写有界一页请求，不走 AKShare 的 10×1000 翻页。
4. 已知限制：股东户数 / 上证e互动 / 深市互动易的底层 HTTP 暂不接入 `BudgetedSession`，不计入 `DATA_HTTP_ATTEMPTS`；每 run 仍受 `SUPPLEMENT_CAPABILITIES`（默认 3）约束，调用前后检查取消。
5. `disclosure_search` 的匹配语义在 2026-11-05 live 验收后修订：改用 CNINFO 服务端标题关键词检索（`searchkey`，空格分隔为 AND）；Gateway 先去日期字面量与 `全文/原文` 填充词，多词 AND 未命中时用最长词再检索一次（每请求 ≤2 次 HTTP）；`isHLtitle=false` 关闭高亮标签。只出现在正文、未出现在标题的词仍返回 typed `capability_empty`，空结果照常消耗一次能力调用。

## 10. 验收标准（设计层）

实现完成后应满足：

1. 专项能在缺口处请求目录内结构化能力，且请求可审计。
2. 无 Wind 等凭证时对应卡不可见、不可调。
3. 挑战/综合阶段写工具请求被拒绝或不存在于 schema。
4. 空结果/失败以 gap 呈现，不转化为方向性结论。
5. 回归：现有 Insight 协议四字段、引用/数值校验、专项隔离、publication barrier 行为不回退。
6. 离线测试覆盖：目录过滤、请求校验、预算拒绝、回灌隔离；真实模型调用另需明确授权。

## 11. 建议落地顺序

1. 冻结能力卡 schema 与 12 张文案（可先不接线）。
2. Gateway 先包装 3～4 个高频卡：`news_search`、`disclosure_search`、`shareholder_count`、`ir_qa`。
3. 接到专项补证口；兼容映射旧 `search_requests`。
4. 量一次真实 run 的阶段 token / 补证次数，再决定预取裁剪幅度与是否打开第 2 次 supplement。

## 12. 开放问题（实现计划前需核对代码后关闭）

1. `capability_requests` 挂在 `InsightSubmission` 同级还是并行 envelope，与现行 strict schema / repair 如何最小改动。
2. 与现行三轮网页补搜、`BudgetBucket.SEARCH_REVIEW` 的精确分账表。
3. Wind 包装走现有 skill/MCP 还是 dataflows 适配器——以「程序路由、凭证不出产物」为准，实现计划里二选一。

---

本文为已批准设计；下一步是单独的实现计划，不在本文展开任务清单或直接改代码。


## 13. 实现进度（2026-11-05）

已落地：能力目录、`CapabilityRequest` 三字段契约、Gateway（disclosure/shareholder/ir_qa）、insight 补证环接线、identity 冻结、相关离线测试与当前态文档同步。

当时仍未做（后续由 §13.3–§13.5 关闭）：Task 6 真实模型 run；其余能力卡（`financials_detail` / `valuation_history` / `northbound_flow` / `industry_peers` / `wind_enrich`）的 Gateway 实现；股东户数/互动问答/一致预期/龙虎榜/增减持适配器接入 `BudgetedSession`；Wind 卡启用。

### 13.1 实现决议（离线补缺后）

1. 补证默认启用（always-on），不新增 `default_config` 开关：每专项上限 2 写在 `graph/insight_research.py`（`CAPABILITY_CALLS_PER_ROLE`）并冻结进 identity，避免为单一常量提前抽象配置面。
2. 卡片 `max_calls_per_run` 按 **run** 生效：Gateway 用 durable `SUPPLEMENT_CAPABILITIES` attempt（stage=`capability.<role>.<card_id>`）计数，resume 不会重花该卡额度；已释放的预约不计。
3. 审计读法写进 [Web 研究操作](../../operations/evidence-research.md#evidence-and-workflow)；当时 Audit Center 的 capability/tool 区尚未渲染 gateway 调用，需读 journal 与报告 gaps（§13.4 已改为从 journal 派生渲染）。
4. 离线覆盖补齐：capability 回灌按 `native_dimension:` 分流到请求专项（其他专项不可见）、round 重放不重复取数、目录 digest 变化触发 resume 冲突。

### 13.2 追加能力卡（2026-11-05）

1. 新接入 `consensus_eps`（THS 一致预期 EPS 样本）、`longhubang`（东财个股龙虎榜近 30 日上榜记录）与 `holder_change`（东财近一年增减持披露，不含回购）。三者都复用仓库已有适配器，Gateway 只做宿主注入、资格化、行数上限与入证。
2. `consensus_eps` 只有实时快照、无归档 vintage：宿主 cutoff 不是当日时返回 typed `capability_unavailable:consensus_eps:capability_not_point_in_time`，不把今天的预测标成历史日期的证据。
3. `longhubang` 只入证上榜记录（日期/原因/净买入/换手），席位明细本次不入证；卡面文案与 `not_for` 同步收窄，避免模型据此推断特定投资者意图。
4. `holder_change` 以公告日 `NOTICE_DATE` 为 `published` 并按 cutoff 截断；窗口内无记录属 `capability_empty`，不伪装成来源失败。
5. 当时三个适配器都不接受 `BudgetedSession`，只计 `SUPPLEMENT_CAPABILITIES`、不计 `DATA_HTTP_ATTEMPTS`（§13.4 已接入）。

### 13.3 Live 验收与修订（2026-11-05）

1. Task 6 已执行一次真实 V9 run（002130，deepseek-flash，762 s 完成）：补证基础设施按设计工作，但 4 次 `disclosure_search` 全部空结果，暴露出整串标题匹配缺陷。详见 [验收备忘](../../reviews/2026-11-05-capability-supplement-live-acceptance.md)。
2. 已按备忘修复：CNINFO `searchkey` 服务端标题检索 + 查询归一化 + 最长词降级 + 关闭高亮；卡片 `query` 收窄为 1–3 个标题关键词。
3. 修复后用同一批真实 query 回归：进展公告、董事会决议、翌日披露报表、股东会决议、乐庭智联均能入证；`股价异常波动公告` 因标题无对应词仍为 typed 空结果。
4. 第二次 live 验收已完成（2026-11-05，用户授权）：能力请求改用标题关键词，3 次调用入证 17 条 capability 事实（经营视图 16 条、事件视图 1 条），并支撑一条 accepted Insight；报告仅剩 `capability_use_search_path`/`capability_budget_exhausted`/`capability_role_limit` 缺口。详见验收备忘。

### 13.4 收尾实现（2026-11-05）

1. 剩余能力卡：`valuation_history`（baostock 日频 PE/PB/PS/PCF，Tushare daily_basic 兜底，最近 60 个交易日、不做分位）、`northbound_flow`（THS 当日沪/深股通累计净买入快照，历史 cutoff 返回 `capability_not_point_in_time`）、`wind_enrich`（Wind 1 年 Beta/年化波动/最大回撤/夏普；要求 `wind_enabled` 且本机 CLI 可解析，否则目录隐藏）。`financials_detail` 与 `industry_peers` 改标 `prefetch_only`：最小证据包已分别采集细项与同行样本，不做同源重复卡。
2. 预算会话：能力适配器接受 run 的 `BudgetedSession`——CNINFO 公告、股东户数、龙虎榜、增减持（经 EastMoney 限速客户端包一层）、THS 一致预期、THS 北向、SSE/CNINFO 互动问答、Tushare 估值兜底均计入 `DATA_HTTP_ATTEMPTS`；baostock TCP 与 Wind CLI 按设计不入 HTTP 预算，仍计 capability 调用。
3. 审计：Audit Center 的 capabilities 分区从 research journal 的 `results`（`capability.batch.*`）派生 batch 摘要（admitted/empty/budget/failure、原因码、提供方、结果 ID），无需新事件类型或前端改动；capability 详情补充可用性/提供方/结果标识。

### 13.5 Challenge 审阅诊断（2026-11-05，离线）

1. 两次 live 验收的 challenge 阶段均失败：第一次 7 条 review 只有 3 条有效，第二次 9 条全部 `unreviewed`。模型有返回、但 review 校验失败且此前没有原因落盘。
2. 已在 `graph/insight_research.py` 记录 `insight.diagnostics.challenge`（`target_unknown` / `blank_text` / `numeric_literal_unbound` / `review_shape_invalid` / `target_missing` / `duplicate_target` 等安全原因码，不保存原文），并在 challenge prompt 约束：每个 I 引用恰好一条 review、不引入新数字（用 `[N]` token 或省略）、只引用已给 E 引用。
3. 已加一次**有界 review repair**：首轮后仅对未覆盖/重复 target 追加一次 `challenge` repair 调用（复用现有 `STRUCTURED_REPAIR` 预算与“只重试失败项”语义），repair 成功则清除重复，仍失败记 `repair_unresolved`；未知派发结果（response_unknown）不会变成新的 repair 尝试。
4. 已执行一次 live 诊断 run（2026-11-05，`run_20261105T123620116834Z_533734b4`）：13 条 accepted Insight、13 条 review；首轮 3 条因 `numeric_literal_unbound` 被拒（I4/I8/I12），有界 repair 修复 I8/I12，仅 I4 残留 `repair_unresolved`，challenge 因 1/13 未审阅仍 failed。根因是 review 文本中的阿拉伯数字/日期未绑定 `[N]`；已加针对性 repair instruction 与 challenge prompt 约束（禁止阿拉伯数字，改用中文数字或保存的 `[N]` token）。详见 [诊断记录](../../reviews/2026-11-05-challenge-review-diagnostics.md)。
5. 验证 run 已完成（2026-11-05，`run_20261105T124829911739Z_e4d054cd`，523 s）：**challenge 阶段 completed、诊断码 0 条**，11 条 review 全部有效（10 challenged + 1 no_counterevidence），无需 repair 即可完成；另有一个独立的 response 阶段失败（`response_operating_quality_unresolved`），不属于本次 challenge 修复范围。
