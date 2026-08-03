# TradingAgents 读者优先工作台优化设计

> 日期：2026-08-03  
> 状态：设计已确认，待实施  
> 决策：采用“方案 A：30 秒决策摘要 + 分层深入”  
> 范围：Web 工作台的信息架构、报告投影、工作流图、历史运行性能、可调整审计侧栏和最近运行可见性  
> 非范围：本文件不修改代码，不删除任何运行、事件、报告、Prompt、工具结果或 artifact

## 1. 文档目的

本文档是后续工程实现与测试的权威指导。目标是把当前偏向“执行监控和审计导出”的工作台，改造成默认服务投资研究读者、同时完整保留技术审计能力的产品。

本文档建立在以下证据之上：

- 对当前 React、FastAPI、SSE、事件存储和报告生成链路的代码审阅。
- 对本地页面 `http://127.0.0.1:8000/` 的真实浏览器验证。
- 对成功运行 `run_20260803T145023364676Z_704b62a0`（`920176.BJ`）的完整持久化复盘。
- 用户确认的产品选择：默认首屏应在 30 秒内回答“结论、理由、风险和下一步”；详细研究与审计按需进入。

本文档在相关范围内细化并取代 `docs/superpowers/specs/2026-07-22-web-research-workbench-optimization-design.md` 的默认阅读呈现方案；其事件真实性、持久化和数据降级原则继续有效。

## 2. 第一性原理与产品不变量

### 2.1 用户的首要任务是做判断，不是观看 Agent 工作

13 个角色是系统的执行拓扑，不是默认的信息架构。默认页面首先回答：

1. 系统对这只股票的研究评级是什么？
2. 本次是否产生可执行动作？
3. 最重要的正面、负面和风险证据是什么？
4. 哪些数据不可靠、缺失或互相冲突？
5. 什么事件会使当前判断成立、失效或需要重估？

### 2.2 完整存储与精简阅读必须分离

- 存储层继续保存完整事件、角色输出、讨论、Prompt、工具结果、供应商调用、报告和 artifacts。
- 阅读层只投影用户完成决策所需的信息。
- “可追溯”意味着每条结论可以进入相关证据上下文，不意味着默认把全部底层对象铺在页面上。

### 2.3 展开是进入上下文，不是无限延长页面

任何详细内容展开后，都必须进入固定高度阅读器、侧栏抽屉或独立审计工作区，并拥有独立滚动容器。禁止继续把完整文章、逐轮讨论或工具结果追加到主页面底部。

### 2.4 技术成功不等于内容完全可信

`completed` 表示运行生命周期和报告发布成功，不表示所有数据、计算和结论均已验证。UI 必须分别表达：

- 运行状态；
- 数据可用性；
- 证据覆盖；
- 事实/计算一致性；
- 研究评级；
- 实际执行动作。

### 2.5 审计事实不可因界面简化而丢失或改写

- 不删除失败 run。
- 不重写既有 `events.jsonl` 或 `complete_report.md`。
- 不把失败状态伪装成其他状态。
- 不以摘要替代原始 artifact；摘要只能引用原始事实。

## 3. 当前系统与问题证据

### 3.1 系统链路

当前系统是 13 角色 LangGraph 研究流程：

```text
Analysts
  → Evidence Steward
  → Bull / Bear debate
  → Research Manager
  → Trader
  → Aggressive / Conservative / Neutral risk debate
  → Portfolio Manager
```

Web 链路为：

```text
React / TypeScript
  → REST snapshot + SSE events + artifact reads
  → FastAPI
  → SingleRunManager / AnalysisRunner / DurableRunObserver
  → LangGraph
  → append-only events + content-addressed artifacts + canonical reports
```

相关实现入口：

- `frontend/src/components/layout/WorkbenchLayout.tsx`
- `frontend/src/state/WorkbenchStore.tsx`
- `frontend/src/hooks/useRunStream.ts`
- `tradingagents/web/api.py`
- `tradingagents/web/manager.py`
- `tradingagents/web/store.py`
- `tradingagents/web/reports.py`
- `tradingagents/reporting.py`

### 3.2 指定成功 run 的规模

运行目录：

`~/.tradingagents/web/runs/run_20260803T145023364676Z_704b62a0`

| 指标 | 事实 |
|---|---:|
| 标的 | `920176.BJ` |
| 状态 | `completed` |
| 最终研究评级 | `Underweight` |
| 运行耗时 | 约 11 分 12 秒 |
| 事件数量 | 1,313 |
| `artifact.written` 事件 | 407 |
| 完成 turn | 23 |
| 运行目录文件 | 338 |
| 运行目录体积 | 约 8.42 MB |
| `events.jsonl` | 920,792 bytes |
| Prompt 快照 | 45 个，约 2.06 MB |
| 完整报告 | 930 行，135,120 bytes |
| 数据失败事件 | 21 |

该 run 是生命周期意义上的成功，但使用了多个降级/不可用数据能力。因此用户级状态应为“已完成 · 数据受限”，而不是无条件绿色“成功”。

### 3.3 完整报告冗长的确定性根因

`tradingagents/reporting.py` 将以下正文分别写入角色报告后，又原样拼接进 `complete_report.md`：

- 四位分析师全文；
- Bull、Bear 的完整多轮 history；
- Research Manager；
- Trader；
- 三位风险角色的完整多轮 history；
- 公共风险信号；
- Portfolio Manager。

指定 run 的 12 份角色 Markdown 合计 132,567 bytes，占完整报告的约 98.1%。所以当前所谓“完整报告”本质上是审计导出包，而不是读者报告。

额外问题：

- Market/Fundamentals 报告含有“Let me write...”一类模型过程话语。
- News 报告重复 Sentiment 内容并直接铺开长篇证据摘录。
- Research Manager 报告再次嵌入四份分析师长摘要。
- 多空 3 轮和风险 3 轮大量重复相同事实，只改变辩论措辞。
- `ResearchDocument` 的 320 字截断只是文本截断，不是语义摘要。
- `FinalReport` 默认解析并挂载完整 Markdown；其后页面又挂载完整时间线。

真实浏览器中打开该 run 后：

| 渲染指标 | 实测 |
|---|---:|
| `body` 可见文本 | 约 123,679 字符 |
| DOM 元素 | 6,298 |
| `article` | 46 |
| 按钮 | 60 |
| 主文档高度 | 约 98,677 px |

### 3.4 最近运行切换卡顿的根因链

浏览器 A/B/A 切换两个成功 run 的可读完成时间实测约 0.58–0.76 秒。根因不是单一 CSS 或 React 小优化问题，而是数据流与挂载策略共同导致：

1. `useRunStream` 每次切换都先读取 snapshot，再从 `after=0` 重放全部 SSE 事件。
2. 后端订阅会读取完整 `events.jsonl` 后再过滤。
3. 每个事件都触发 reducer 和全局 Context value 更新，重型子树广泛重渲染。
4. `MarketChart` 依赖全局 `latest_sequence`，事件推进可能反复触发行情投影请求。
5. `ResearchDocument` 的所有已提交卡片挂载时立即读取 artifact。
6. Timeline 预取多个 turn response；FinalReport 同时读取并解析 135 KB Markdown。
7. 快速切换时 snapshot、market 和 artifact HTTP 请求没有真正取消，只忽略旧响应。
8. 选中历史 completed run 在 SSE 重放到终态后会误触发 `history.refresh()`。
9. 运行历史刷新遍历全部 run；读取 snapshot 又会扫描各自事件日志的末尾序列。
10. 切换开始时旧 run state 没有立即撤下，用户会短暂看到旧内容，强化“点击无响应”的感受。

### 3.5 工作流图难看的根因

`WorkflowMap.tsx` 当前：

- 定义了 SVG arrow marker，但路径没有绑定 `markerEnd`，箭头不会显示。
- 所有边使用 cubic Bézier 曲线。
- 所有边都按“源卡右中点 → 目标卡左中点”连接。
- 同阶段内上下排列的角色会产生反向、回绕和交叉。
- 阶段交接、对抗和汇聚三种语义混在同一自由路由层。

### 3.6 右侧栏不可调整的根因

三栏布局固定为：

```css
288px minmax(600px, 1fr) 340px
```

当前没有 splitter、Pointer Event、宽度状态、键盘控制或持久化偏好，所以 Inspector 必然固定为 340px。

### 3.7 失败 run 出现在最近运行的根因

这是旧产品契约，不是漏判：

- `RunStore.list_runs()` 返回全部状态。
- `GET /api/runs` 原样返回。
- `useRunHistory` 原样保存。
- `RunHistory` 明确定义并渲染 failed 徽标。
- 现有测试还断言 failed 必须可见。

当前本地 30 个 run 中约 23 个为 failed；失败记录占约 77%，显著降低“最近运行”的有效信息密度。

### 3.8 指定 run 暴露的内容一致性风险

多空讨论把：

```text
70.8 元 × 5,000 万股
```

计算成 `3.54 亿元`，正确结果应为 `35.4 亿元`。后续 Portfolio 使用的 PE 38–46 倍、PB 约 7 倍又隐含采用了正确数量级，但没有明确纠正前序讨论。

这说明当前 Evidence PASS 只可解释为身份/覆盖门槛通过，不能解释为所有事实和算术均已验证。默认摘要必须揭示冲突，不能把争议数字包装成确定事实。

## 4. 目标体验与信息架构

### 4.1 页面职责

```text
┌──────────────┬──────────────────────────────────────────┬─┬──────────────┐
│ 分析输入      │ 标的 · 研究评级 · 数据质量               │↔│ 按需审计侧栏 │
│              ├──────────────────────────────────────────┤ │              │
│ 最近运行      │ 30 秒决策摘要                            │ │ 当前所选依据 │
│ 排除 failed   │ 结论 / 动作 / 驱动 / 风险 / 验证节点     │ │ 角色执行事实 │
│              ├──────────────────────────────────────────┤ │ 来源与工具   │
│              │ 研究依据                                  │ │ Prompt/配置  │
│              │ 主题卡 / 讨论摘要 / 完整过程 / 完整导出   │ │              │
└──────────────┴──────────────────────────────────────────┴─┴──────────────┘
```

### 4.2 默认 30 秒摘要（L1）

打开成功 run 后首屏只显示以下内容，目标控制在约 400–700 个中文字：

1. **运行结果**：完成状态、数据质量、耗时。
2. **研究评级**：例如 `Underweight`。
3. **执行事实**：例如 `Hold 0`；必须与研究评级分开。
4. **一句话结论**：2–4 句以内的 Executive Summary。
5. **核心驱动**：最多 5 条，带方向、重要度和证据引用。
6. **主要风险/反方异议**：最多 3 条。
7. **催化剂与验证节点**：日期或条件。
8. **失效条件**：哪些事实会推翻当前判断。
9. **数据可信度**：降级、不可用和冲突能力。

对指定 run，首屏应清楚区分：

- 研究评级：低配（Underweight）。
- 本次执行：Hold 0。
- 未执行减仓的原因：没有提供组合账户和可交易头寸。

### 4.3 研究依据（L2）

使用四张主题卡，而不是四篇连续长文：

- 市场与技术；
- 基本面；
- 新闻与事件；
- 情绪与资金。

每张卡默认只展示：

- 方向；
- 置信度；
- 最多 3 条主题结论；
- 最大数据限制；
- 证据数量和“查看完整分析”。

News 与 Sentiment 可以在同一主题区域以 Tab 切换，避免连续重复阅读；原始新闻摘录只进入证据阅读器。

### 4.4 讨论摘要（L3）

多空讨论和风险讨论默认投影为：

- 共识事实；
- 核心分歧；
- 新增证据；
- 哪些观点在后续轮次发生变化；
- 最终裁决；
- 剩余不确定性。

不默认展示逐轮原文。用户选择“查看 3 轮完整讨论”后，在固定高度阅读器内按轮次和角色定位。

Agent 内部仍接收完整上下文；读者摘要不反向限制 Agent 的执行输入。

### 4.5 高级审计（L4）

右侧栏或全屏审计工作区提供以下 Tab：

- 轮次摘要；
- 完整原文；
- 输入与 Prompt；
- 工具调用；
- 原始数据；
- 证据与来源；
- Artifact 元数据；
- 有效配置。

所有内容按需加载、可取消、可缓存。长列表使用虚拟滚动，并保留主报告滚动位置。

### 4.6 完整报告的重新定位

- `complete_report.md` 继续原样发布，作为“完整审计报告/下载导出”。
- 它不再作为默认主页面正文。
- 点击“查看完整报告”进入独立阅读器，不在主页面向下展开。
- 阅读器提供目录、章节定位、独立滚动和关闭后返回原位置。

## 5. 读者投影数据设计

### 5.1 不新增总结 Agent，但必须保存同一调用中的结构化公共输出

系统已经在同一次模型调用中产生以下类型化公共对象：

- Research Manager：`ResearchPlan`，含 recommendation、rationale、strategic actions 和四类 `strategy_signals`；
- Trader：`TraderProposal`，含 action、reasoning、价格与仓位字段；
- 风险角色：`RiskDebateSignal`，含 public evidence summary、conviction 和 confidence；
- Portfolio Manager：`PortfolioDecision`，含 rating、executive summary、thesis、time horizon、execution 和最多 5 个 top drivers。

当前实现把这些对象渲染成 Markdown 后丢弃 typed object。后续实现必须同时持久化类型化公共输出和兼容 Markdown；不得增加第二次 LLM 总结调用，也不得从 Markdown 反向解析。

为补齐读者层需要但当前 schema 没有的字段，在原有同一次结构化调用中增加 optional `reader_fields`，默认 `null`，保持旧 provider/fallback 兼容：

- `ResearchPlan.reader_fields.public_digest`：共识、分歧、观点变化和剩余不确定性；
- `ResearchStrategySignal.reader_fields.key_findings`：每个研究 lens 最多 3 条公共结论；
- `RiskDebateSignal.reader_fields.evidence_summary_refs`：风险摘要对应的允许引用 ID；
- `DecisionDriver.reader_fields.evidence_ref_ids`：保留旧 `evidence_ref` 文本用于 Markdown，同时提供可解析引用；
- `PortfolioDecision.reader_fields`：Executive Summary 引用、催化剂和失效条件。

这些字段只保存公开结论，不保存私有推理。结构化 provider 不支持新增 optional reader fields 或 fallback 到 free text 时，相关部分标记不可用，不进行字符串推断。

### 5.2 每个字段的唯一来源

| ReaderBrief 字段 | 唯一来源 | 确定性规则 |
|---|---|---|
| run/ticker/status/timestamps | `RunSnapshot` | 原样复制 committed snapshot |
| research rating | committed `PortfolioPublicOutputV1.rating` | 不从正文或 `final_signal` 反向解析 |
| execution action/quantity | `PortfolioPublicOutputV1.execution` | 按 5.3 的 requested/effective 合并规则 |
| executive summary | `PortfolioPublicOutputV1.reader_fields.executive_summary` | reader fields 不可用时为 null 并声明 omission |
| time horizon/price target | `PortfolioPublicOutputV1` | 空值保持 `null` |
| top drivers | `PortfolioPublicOutputV1.top_drivers` | evidence ref 必须可解析且属于同一 run |
| risks | direction=`risk` 的 top drivers + 高/严重数据冲突 | 不生成新的自然语言风险 |
| catalysts/invalidation | `PortfolioPublicOutputV1.reader_fields` | null 表示缺失；空数组表示确认没有 |
| analyst cards | `ResearchPublicOutputV1.strategy_signals` | conviction/confidence/abstain 原样；findings 最多 3 条 |
| debate digest | `ResearchPublicOutputV1.public_digest` | 没有显式字段时不展示“观点变化” |
| risk consensus | committed `RiskDebateSignal` 集合 | 使用现有确定性聚合器；不新增主观置信度等级 |
| data quality | run degradations + typed consistency results | 取最严重等级；不由 LLM 决定 |
| audit counts/index | committed events/artifact metadata | 仅计入当前 `source_sequence` 以前的事实 |

### 5.3 类型化证据引用

所有用户可见的实质性研究 claim 使用以下契约；运行元数据和 UI 状态文案不需要 claim 引用。

```ts
type EvidenceTargetV1 =
  | { kind: "artifact"; artifact_id: string }
  | { kind: "turn"; turn_id: string }
  | { kind: "evidence_item"; ledger_artifact_id: string; item_id: string }
  | { kind: "data_call"; data_call_id: string };

interface EvidenceRefV1 {
  ref_id: string;                 // sha256(RFC 8785 JCS UTF-8 target)
  run_id: string;
  label: string;
  target: EvidenceTargetV1;
  resolution_status: "available" | "target_missing";
}

interface PublicClaimV1 {
  claim_id: string;
  text: string;
  evidence_ref_ids: string[];     // required, length >= 1
}
```

模型调用使用不含 `claim_id` 的输入形状；服务端校验后生成 `PublicClaimV1`：

```ts
interface ModelClaimInputV1 {
  text: string;                    // 1..600 chars
  evidence_ref_ids: string[];      // 1..8, only prompt allowlist IDs
}
```

规则：

1. 模型只能返回 Prompt 中提供的允许引用 ID；服务端拒绝任意新 ID。
2. `ref_id` 由服务端对 `EvidenceTargetV1` 执行 RFC 8785 JSON Canonicalization Scheme，取 UTF-8 bytes 的小写 SHA-256 hex；模型不负责生成哈希。
3. 每个 `PublicClaimV1` 至少一个引用；无引用 claim 不进入默认摘要。
4. ref 的 `run_id` 必须与 brief 相同；available 目标必须在 `source_sequence` 前 committed。
5. Resolver 不读取文件系统 locator 作为浏览器参数；只接受已校验的 ID。
6. 发布时目标存在则写 `available`。之后目标丢失，或 legacy 重建时已丢失，写/返回 `target_missing`；claim 仍显示，但默认摘要标记“来源不可用”且不显示为已验证。
7. hash、shape、跨 run 或 sequence 越界是 structural ref error，会使构建失败；`target_missing` 是可表达的数据状态，不使 projection 失效。

#### 上游公共 artifact 契约

每次现有结构化调用完成后，投影层写以下公共 artifact；所有字段 required，nullable/空列表规则与 ReaderBrief 相同：

```ts
interface ResearchSignalPublicV1 {
  lens: "market" | "fundamentals" | "news" | "sentiment";
  conviction: number | null;       // [-1,1]; abstain=true iff null
  confidence: number;              // [0,1]
  abstain: boolean;
  rationale: string;
  reader_fields_status: "available" | "unsupported" | "missing";
  key_findings: ModelClaimInputV1[] | null; // [] validly none; null unavailable
}

interface ResearchPublicOutputV1 {
  schema_version: 1;
  run_id: string;
  turn_id: string;
  committed_sequence: number;
  recommendation: "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell";
  rationale: string;
  strategic_actions: string;
  strategy_signals: ResearchSignalPublicV1[];
  public_digest: {
    agreed_facts: ModelClaimInputV1[];
    key_disagreements: ModelClaimInputV1[];
    changed_views: ModelClaimInputV1[];
    remaining_uncertainties: ModelClaimInputV1[];
  } | null;
}

interface TraderPublicOutputV1 {
  schema_version: 1;
  run_id: string;
  turn_id: string;
  committed_sequence: number;
  action: "Buy" | "Hold" | "Sell";
  reasoning: string;
  entry_price: number | null;
  stop_loss: number | null;
  position_sizing: string | null;
}

interface RiskSignalPublicOutputV1 {
  schema_version: 1;
  run_id: string;
  turn_id: string;
  committed_sequence: number;
  role: "aggressive" | "conservative" | "neutral";
  conviction: number | null;
  confidence: number;
  abstain: boolean;
  evidence_summary_text: string;
  reader_fields_status: "available" | "unsupported" | "missing";
  evidence_summary: ModelClaimInputV1 | null;
}

interface ExecutionSummaryV1 {
  availability: "ready" | "unavailable";
  requested_action: "Buy" | "Hold" | "Sell" | null;
  requested_quantity: number | null;
  effective_action: "Buy" | "Hold" | "Sell" | null;
  effective_quantity: number | null;
  reason_code: string | null;
}

interface PortfolioConstraintOutcomeV1 {
  schema_version: 1;
  run_id: string;
  turn_id: string;
  committed_sequence: number;
  requested_action: "Buy" | "Hold" | "Sell";
  requested_quantity: number;
  effective_action: "Buy" | "Hold" | "Sell";
  effective_quantity: number;
  reason_code: string;
}

interface PortfolioPublicOutputV1 {
  schema_version: 1;
  run_id: string;
  turn_id: string;
  committed_sequence: number;
  rating: "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell";
  executive_summary_text: string;
  investment_thesis: string;
  price_target: number | null;
  time_horizon: string | null;
  execution: ExecutionSummaryV1;
  top_drivers: Array<ModelClaimInputV1 & {
    direction: "positive" | "negative" | "risk";
    importance: number;
  }>;
  reader_fields_status: "available" | "unsupported" | "missing";
  reader_fields: {
    executive_summary: ModelClaimInputV1;
    catalysts: ModelClaimInputV1[];               // 0..3; [] means validly none
    invalidation_conditions: ModelClaimInputV1[]; // 0..3; [] means validly none
  } | null;
}
```

Research/Risk 的 `reader_fields_status=available` 当且仅当对应 claim/list 非 null；`[]` 表示模型明确没有适用 findings。Risk reader fields 不可用时，conviction/confidence/abstain 仍进入确定性 `risk_consensus`，但 evidence summary 不进入 L1，并产生 omission。

`reader_fields_status=available` 当且仅当 `reader_fields != null`；`unsupported/missing` 当且仅当 `reader_fields == null`。因此 `[]` 与“字段不可用”不会混淆。

公共 artifact 使用 `application/json`，由现有 artifact store 原子写入并产生 `artifact.written`：

| kind | locator 形状 | 选择规则 |
|---|---|---|
| `public-research` | `public/<turn_id>/research-v1.json` | 最新 committed Research Manager turn |
| `public-trader` | `public/<turn_id>/trader-v1.json` | 最新 committed Trader turn |
| `public-risk-signal` | `public/<turn_id>/risk-signal-v1.json` | 每个风险角色在 PM turn 之前的最新 committed signal |
| `public-portfolio` | `public/<turn_id>/portfolio-v1.json` | 最新且唯一 committed Portfolio Manager turn |

`turn_id` 必须先通过现有安全 ID 校验。文件可以在 output-ready 阶段写入，但只有对应 graph step applied 后才可被 ReaderBrief 选择；abandoned candidate 保留审计但不进入投影。

execution 合并规则：

1. `requested_*` 来自模型原始 `PortfolioDecision`。
2. 同一 PM turn 的 committed `PortfolioConstraintOutcomeV1` 存在时，`effective_*` 与 `reason_code` 只取该事件。
3. 没有 portfolio context 时，确定性结果为 `Hold 0 / portfolio_context_unavailable`。
4. 有 portfolio context 却缺少 committed clamp outcome 时，`availability=unavailable`，effective 字段为 `null`；不得回退到 requested 值。
5. 多个 committed clamp outcome 属于完整性错误，brief unavailable，原始 run 仍可审计。

风险列表转换规则：

1. critical consistency conflicts；
2. high consistency conflicts；
3. Portfolio top drivers 中 direction=`risk` 的项，按 importance 降序；
4. 按 claim/ref 内容哈希去重后取前 5 条。

冲突文本只能由 `message_code` 对应的本地化模板生成，引用沿用 conflict 的 `evidence_ref_ids`；medium conflict 只进入 DataQuality，不进入 L1 risks。

解析接口：

```http
GET /api/runs/{run_id}/evidence-refs/{ref_id}
```

成功返回目标类型、角色/时间/来源元数据和现有 artifact/turn/data-call API 的安全读取链接。错误：

- `404 ref_not_found`：引用不存在；
- `409 ref_run_mismatch`：跨 run 引用；
- `410 ref_target_missing`：索引存在但目标丢失或损坏。

### 5.4 `ReaderBriefV1` 实现契约

`ReaderBriefV1` 是 `application/json` artifact，固定位置为：

```text
<run_dir>/projections/reader-brief-v1.json
```

核心类型：

```ts
type BriefAvailability = "full" | "partial" | "unavailable";
type DataQualityLevel = "healthy" | "limited" | "conflicted" | "unknown";
type Rating = "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell";
type BriefOmissionCode =
  | "research_output_missing" | "trader_output_missing" | "risk_signals_missing"
  | "portfolio_reader_fields_missing" | "catalysts_missing" | "risk_signal_refs_missing"
  | "executive_summary_missing" | "driver_refs_missing"
  | "invalidation_conditions_missing" | "analyst_findings_missing"
  | "debate_digest_missing" | "data_quality_unknown";

interface ReaderBriefV1 {
  schema_version: 1;
  run_id: string;
  ticker: string;
  source_sequence: number;
  generated_at: string;
  availability: BriefAvailability;
  omissions: BriefOmissionCode[];
  research_rating: Rating;
  execution: ExecutionSummaryV1;
  executive_summary: PublicClaimV1 | null;
  price_target: number | null;
  time_horizon: string | null;
  drivers: Array<PublicClaimV1 & {
    direction: "positive" | "negative" | "risk";
    importance: number;
  }>;
  risks: PublicClaimV1[];
  catalysts: PublicClaimV1[];
  invalidation_conditions: PublicClaimV1[];
  analyst_cards: Array<{
    lens: "market" | "fundamentals" | "news" | "sentiment";
    conviction: number | null;
    confidence: number;
    abstain: boolean;
    findings: PublicClaimV1[];
  }>;
  debate_digest: {
    agreed_facts: PublicClaimV1[];
    key_disagreements: PublicClaimV1[];
    changed_views: PublicClaimV1[];
    remaining_uncertainties: PublicClaimV1[];
  };
  risk_consensus: {
    conviction: number | null;
    disagreement: "none" | "tight" | "wide" | "mixed";
    abstained_roles: string[];
  };
  data_quality: DataQualityV1;
  evidence_refs: EvidenceRefV1[];
}
```

所有字段 required；“不适用/没有”使用空列表或 `null`，不是省略字段。Portfolio `reader_fields=available` 且 catalysts/invalidation 为 `[]` 时是合法的“没有”，不产生 omission；`unsupported/missing` 时 executive summary 为 `null`，两个列表为空，并加入 `portfolio_reader_fields_missing`、`executive_summary_missing`、`catalysts_missing`、`invalidation_conditions_missing`。Research key findings 为 null 时该 lens findings 输出 `[]` 并加入 `analyst_findings_missing`；合法 `[]` 不加。Risk evidence summary 为 null 时仍聚合 numeric consensus，但加入 `risk_signal_refs_missing`。旧 DecisionDriver 只有自由文本 `evidence_ref` 而没有允许 ID 时，该 driver 不进入 L1，并加入 `driver_refs_missing`。任一 omission 使 brief 为 `partial`。缺少整个 committed Portfolio public output 时 `availability=unavailable` 且不写 brief artifact，由 RunView envelope 表达原因。

### 5.5 `RunViewProjectionV1` 与 envelope

物化文件固定位置：

```text
<run_dir>/projections/run-view-v1.json
```

API 始终返回 envelope，避免 legacy/error 使用不同 JSON shape：

```ts
type ProjectionStatus = "ready" | "partial" | "legacy_fallback" | "unavailable";
type ProjectionReasonCode =
  | "legacy_no_typed_outputs" | "brief_generation_failed"
  | "projection_corrupt" | "projection_rebuild_failed"
  | "unsupported_schema" | null;

interface RunViewEnvelopeV1 {
  schema_version: 1;
  projection_status: ProjectionStatus;
  reason_code: ProjectionReasonCode;
  source_sequence: number;
  terminal: boolean;
  view: RunViewProjectionV1;
}

interface RunViewProjectionV1 {
  run: RunSummaryV1;
  brief: {
    availability: BriefAvailability;
    reason_code: string | null;
    value: ReaderBriefV1 | null;
  };
  workflow: WorkflowProjectionV1;
  section_index: SectionIndexItemV1[];
  data_quality: DataQualityV1;
  available_audit_counts: {
    turns: number;
    prompts: number;
    tool_calls: number;
    data_calls: number;
    artifacts: number;
    reports: number;
  };
  legacy_fallback: {
    final_signal: string | null;
    portfolio_artifact_id: string | null;
    complete_report_artifact_id: string | null;
  } | null;
}

type RunStatusV1 =
  | "created" | "running" | "cancel_requested" | "completed"
  | "failed" | "cancelled" | "interrupted";

interface RunSummaryV1 {
  run_id: string;
  ticker: string;
  status: RunStatusV1;
  created_at: string;
  completed_at: string | null;
  latest_sequence: number;
  final_signal: string | null;
  duration_ms: number | null;
  data_quality_level: DataQualityLevel;
}

type WorkflowStageIdV1 =
  | "analysts" | "evidence" | "research"
  | "trading" | "risk" | "portfolio";
type WorkflowStatusV1 =
  | "waiting" | "running" | "completed" | "failed"
  | "cancelled" | "interrupted" | "skipped";

interface WorkflowActorV1 {
  actor_id: string;
  status: WorkflowStatusV1;
  latest_turn_id: string | null;
  completed_turns: number;
}

interface WorkflowStageV1 {
  stage_id: WorkflowStageIdV1;
  status: WorkflowStatusV1;
  actors: WorkflowActorV1[];
}

interface WorkflowProjectionV1 {
  total_roles: 13;
  completed_roles: number;
  active_actor_id: string | null;
  stages: WorkflowStageV1[];       // fixed six-stage order
}

type SectionIdV1 =
  | "brief" | "market" | "fundamentals" | "news" | "sentiment"
  | "debate" | "research_verdict" | "trading" | "risk"
  | "portfolio" | "complete_report" | "audit";

interface SectionIndexItemV1 {
  section_id: SectionIdV1;
  label: string;
  availability: "ready" | "partial" | "unavailable";
  artifact_ids: string[];
  turn_ids: string[];
}
```

上述类型与 `DataQualityV1` 必须由后端 Pydantic/JSON Schema 定义并生成前端类型；数字字段均要求有限值，计数非负。未知 enum 值前端显示“版本不支持”，不得静默当成成功。

### 5.6 投影所有权、写入和生命周期

`RunProjectionPublisher` 是唯一 writer，属于 Web/observability 投影层，不进入 Agent 业务逻辑。`ReaderBriefPublisher` 与 `RunViewProjector` 是它在同一 per-run lock 内调用的纯构建器，不得自行落盘或另取锁。

写入协议：

1. 获取现有 per-run lock。
2. 只读取 committed snapshot、events 和 typed public artifacts。
3. 捕获最高 committed `source_sequence=N`。
4. 在同目录写临时文件，校验 JSON Schema 与 ref 的 hash/shape/run/sequence；目标缺失写 `target_missing`，不视为 structural failure。
5. `fsync(file)`，`os.replace` 到版本化固定路径，`fsync(directory)`。
6. 释放 lock 后才允许订阅者观察新的 projection version。

发布时机：

- `graph.step_applied` 后发布 live partial view；连续 applied 事件允许 250ms 合并，但不得跨 run 状态边界。
- `report.updated` 只在对应 graph step committed 后进入 view。
- 成功流程先发布 canonical reports，再发布 ReaderBrief 或明确记录 brief failure，之后 append `run.completed`，最后强制刷新 terminal RunView。
- failed/cancelled/interrupted 追加终态事件后强制刷新 terminal RunView；brief 可以 partial/unavailable。
- terminal view 当 `source_sequence == run.latest_sequence` 时视为不可变派生物；修复损坏时只能从相同事实确定性重建，不能改变业务含义。

读取与 SSE 竞态规则：

```text
GET /view 返回 source_sequence=N
  → 客户端先渲染 view
  → 订阅 SSE after=N
  → N 之后发生的事件由 replay/live 补齐
```

即使 GET 与订阅之间发生事件也不会丢失。candidate/output-ready 不进入 committed view。

### 5.7 legacy、损坏和版本升级

- 旧 run 没有 typed public artifact：`projection_status=legacy_fallback`，`brief.availability=unavailable`，返回 final signal 和原始 Portfolio/complete report 入口。
- 旧 run 有足够 typed artifact：首次 GET 可确定性懒重建并原子持久化；不得从 Markdown 猜字段。
- projection JSON 损坏或 structural ref 校验失败：忽略该派生缓存并尝试重建；不修改 events/reports。单纯 `target_missing` 不触发重建失败或 unavailable shell。
- 重建仍失败：HTTP 200 返回 `projection_status=unavailable`、稳定 `reason_code` 和最小 run shell，页面仍可进入原始审计。
- run 不存在返回 `404 run_not_found`；run_id 非法返回 `422 invalid_run_id`。
- 遇到高于客户端支持的 schema：前端显示版本不支持；服务端将当前支持版本写入另一个版本化文件，不覆盖未知文件。
- 本项目不做全库强制 backfill。批量迁移工具不属于本次范围。

## 6. API 与状态边界

### 6.1 最近运行 API

`GET /api/runs` 无 `view` 参数时继续返回现有数组，保持旧客户端兼容。

新读者列表：

```http
GET /api/runs?view=recent&limit=20&cursor=<opaque>
```

返回：

```ts
interface RecentRunsPageV1 {
  schema_version: 1;
  items: RunSummaryV1[];
  next_cursor: string | null;
}
```

契约：

- `limit` 默认 20，范围 1–100；非法值返回 `422 invalid_limit`。
- 先按 eligible status 过滤，再分页。
- eligible：created、running、cancel_requested、completed、cancelled、interrupted；唯一排除 failed。
- 稳定排序：`created_at DESC, run_id DESC`。
- cursor 是带版本和筛选签名的 base64url opaque token，内部记录最后一项的 `created_at + run_id`；客户端不得解析。
- cursor 失效、损坏或用于不同 filter 时返回 `400 invalid_cursor`。
- 并发新增 run 不得造成同一游标链中的重复项；允许新项只在刷新第一页后出现。
- `next_cursor` 指向最后一个 eligible item；failed 项不能占用页容量。

失败可见性状态机：

- live run 变 failed 时，主区域保留失败详情和 retry。
- 最近运行在收到终态事件后移除该卡；不得因此清空当前主区域。
- 用户切换或刷新后，failed 不再从 recent API 返回。
- `GET /api/runs/{run_id}`、events、artifacts 和 retry 继续可用。
- cancelled/interrupted 不得被本需求顺带隐藏。

### 6.2 轻量视图 API

```http
GET /api/runs/{run_id}/view
```

返回 `RunViewEnvelopeV1`。除 run 不存在/ID 非法外，投影不可用也返回 200 envelope，让 UI 可以进入 legacy 审计。

历史打开流程：

```text
读取 /view
  → 立即渲染 brief/workflow 或 legacy shell
  → 从 envelope.source_sequence 增量订阅 SSE
  → 用户展开时读取具体 artifact
```

禁止 terminal 历史 run 每次从 `after=0` 重放全部事件。

### 6.3 证据与 Artifact 请求

- 所有前端 GET helper 接受 `AbortSignal` 并传给 `fetch`。
- 以 `run_id + artifact_id` 或 `run_id + ref_id` 为统一缓存键。
- 同键并发请求去重。
- 缓存使用有界 LRU，不得无限增长。
- 切换 run 后，旧 run 未完成 fetch 必须由 `AbortController.abort()` 真正取消；仅设置 `cancelled=true` 不满足要求。
- 排队但未发出的旧 run 工作从并发队列移除；迟到响应不得写入新 run UI。
- SSE 使用现有 close/abort，并从新 view watermark 连接。

## 7. 工作流图设计

### 7.1 两层线路模型

第一层是六阶段水平主干：

```text
分析师团队 → 证据管理 → 多空研究 → 交易 → 风险管理 → 组合管理
```

使用单向直线、明确箭头和固定 lane。主干表达阶段顺序，不直接连接任意角色卡。

第二层是阶段内部关系：

- 四位分析师通过汇聚母线进入证据管理员。
- Bull 与 Bear 使用短双向线或 `VS`，再汇聚到 Research Manager。
- Trader 为单节点，不需要内部边。
- Aggressive、Neutral、Conservative 通过短正交线汇聚到 Portfolio Manager 的阶段出口。
- 阶段出口连接下一阶段主干。

### 7.2 路由约束

- 只允许水平、垂直和带小圆角的正交折线。
- 禁止自由 cubic Bézier。
- 线路不得穿过节点卡片或文字。
- 固定 lane 分别承担主干、汇聚和对抗语义。
- 箭头通过真实 `marker-end` 或等价方式绑定到路径。
- completed/active/error 只改变颜色、虚实和粗细，不改变几何位置。
- 装饰性连线 `pointer-events: none`。
- 颜色不是唯一状态表达；同时保留文字、图标或线型。

### 7.3 响应式

- 宽屏：六阶段水平图。
- 中等宽度：允许阶段横向滚动，但保持正交主干。
- 窄屏：切换为纵向 stepper；不缩小整张图，不显示容易交叉的内部装饰线。

### 7.4 几何测试不变量

- 每条路径存在可见方向箭头。
- 所有路径段均为正交段；若有圆角，只用于相邻正交段过渡。
- 任何路径的包围盒与非端点卡片不相交。
- 同一 lane 的边不发生不必要交叉。
- 关键 viewport 截图中不存在回绕、穿卡或箭头缺失。

## 8. 可调整 Inspector 设计

### 8.1 桌面端

在主内容与 Inspector 之间插入 8–12px 可命中分隔柄，视觉线宽保持 1px。

```html
<div role="separator"
     aria-orientation="vertical"
     aria-valuemin="320"
     aria-valuemax="640"
     aria-valuenow="340" />
```

行为：

- Pointer Events + `setPointerCapture`。
- 拖动时通过 `requestAnimationFrame` 更新 CSS 变量 `--inspector-width`。
- 不在每个 `pointermove` 写 React state。
- `pointerup` 后才提交偏好并写入本地持久化。
- 宽度使用 `clamp(320px, savedWidth, min(640px, 45vw))`；在桌面断点内保证最大值不小于最小值。
- 默认 340px。
- 双击恢复默认宽度。
- ArrowLeft/ArrowRight 每次调整 16px。
- Home/End 调到最小/最大。
- 焦点、hover 和拖动中状态均有可见反馈。

### 8.2 窄屏

在 `viewport < 1100px` 时：

- 关闭横向 splitter。
- Inspector 变为右侧抽屉或底部 sheet。
- 主报告保持全宽。
- 关闭抽屉后恢复原主报告滚动位置。

### 8.3 持久化

- 保存的是用户界面偏好，不进入 run 事实或审计事件。
- 存储值必须在读取时重新 clamp，避免窗口变化后恢复非法宽度。
- 服务端渲染或无本地存储环境使用 340px 默认值。

## 9. 性能架构

### 9.1 修复优先级

#### P0：移除确定性请求和重放放大

1. 历史 run 改读 `RunViewProjectionV1`，不从序列 0 重放。
2. `MarketChart` 只依赖 `market_projection_version` 或相关 artifact 集变化，不依赖所有事件的 `latest_sequence`。
3. 只有真实 live run 从非终态进入终态时刷新历史；打开历史 completed run 不触发 refresh。
4. 运行列表不得为计算 `latest_sequence` 扫描每个 `events.jsonl`；使用原子维护的 run snapshot 或轻量索引。
5. 切换开始时立即高亮目标卡、撤下旧正文并显示目标骨架。
6. snapshot、market、artifact 请求接入真正的取消。

#### P1：隔离渲染和加载

1. 拆分 selection/history context 与 active-run projection context。
2. 让 RunHistory 只订阅选中 ID 和历史数据，不订阅每个 SSE state。
3. replay 以固定 64 事件为一批 fold，同一 animation frame 最多发布一次 React projection；终态事件立即 flush。
4. 默认保存最近 3 个 run 的 LRU 投影缓存；容量是单一配置常量，测试固定为 3。
5. 默认只挂载 brief；主题报告、讨论、完整报告和审计组件按需挂载。
6. artifact 统一缓存、去重、并发限制和取消。
7. Timeline/审计长列表虚拟化。

#### P2：体验增强

- 使用 transition/skeleton 平滑非阻塞更新。
- 在缓存命中时恢复每个 run 的阅读位置和当前选区。
- 提供可观察的性能指标，避免后续回归。

### 9.2 缓存正确性

- 缓存键至少包括 `run_id + schema_version + source_sequence`。
- live run 有新 committed sequence 时旧投影失效或增量更新。
- terminal run 的 canonical 投影可长期缓存，但 artifact 权限/存在性仍由服务端校验。
- 不能跨 run 共享 selected turn、手动选择标记或审计正文。

### 9.3 性能预算

| 场景 | 预算 |
|---|---:|
| 点击历史卡片到视觉选中反馈 | `< 100ms` |
| 缓存 A/B/A 回切到摘要可读 | `< 150ms` |
| 冷启动轻量投影 p95 | `< 400ms` |
| 主线程长任务 | 无 `> 50ms` |
| terminal 历史 run 的 market-view | 每次打开最多 1 次；缓存回切 0 次 |
| 切换后的旧 run 请求 | 已发 fetch 全部 abort；排队任务全部移除 |
| 默认首屏 artifact | 不加载完整报告、逐轮原文、Prompt、工具结果 |

### 9.4 可复现测量协议

自动化基准固定为：生产构建、Playwright Chromium、1280×800 viewport、localhost、无人工 CPU/网络节流。CI 使用固定 runner 规格并在测试报告记录 CPU、内存、浏览器版本和 commit SHA。

Fixture：

- A：1,313 events、135,120-byte complete report 的 completed run；
- B：另一条至少 1,000 events、100 KB complete report 的 completed run；
- 两条 run 都预生成合法 `RunViewProjectionV1`；另保留一组无 projection 的 legacy fixture。

定义：

- **冷启动**：新 browser context，前端 LRU/HTTP cache 为空，首次选择 A；允许操作系统文件缓存，不允许预先访问 A 的 `/view`。
- **暖回切**：同一 context 已成功打开 A、B 后，再执行 A/B/A。
- 每个场景先预热 3 次，再独立测量 30 次；p95 使用 nearest-rank 第 29 个有序样本。

测量点：

| 指标名 | 起点 | 终点 |
|---|---|---|
| `ta.run_select.feedback_ms` | history item `pointerup` | 新 item active 样式下一次 paint |
| `ta.run_view.ready_ms` | 同一 `pointerup` | 目标 brief 根节点 `data-ready=true` 后下一次 paint |
| `ta.longtask.max_ms` | 切换开始 | brief ready 后 500ms；由 `PerformanceObserver(longtask)` 记录 |
| `ta.request.abort_count` | 切换开始 | 所有旧 run controller 进入 aborted |
| `ta.market_view.request_count` | 目标 run 选择 | brief ready 后 1s 的同 run 请求计数 |
| `ta.replay.event_count` | SSE 连接 | 目标 view ready；terminal 历史 run 期望 0 或仅 N 后新增事件 |

若浏览器不支持 Long Tasks API，测试必须明确 skip 该断言并由 Chrome CI job 覆盖，不得默认为通过。

## 10. 内容质量与发布前一致性

### 10.1 校验输入只能来自结构化事实

一致性检查不得解析 Agent Markdown。数据层或 Evidence Ledger 必须提供 committed `MetricFactV1`：

```ts
type MetricId =
  | "price"
  | "shares_outstanding"
  | "market_cap"
  | "shareholders_equity"
  | "ttm_net_income"
  | "pb"
  | "pe";

interface MetricFactV1 {
  fact_id: string;
  metric: MetricId;
  normalized_value: string;       // base-10 Decimal string, never binary float
  unit: "currency" | "shares" | "ratio";
  currency: string | null;         // ISO 4217 when unit=currency
  as_of: string | null;
  period_start: string | null;
  period_end: string | null;
  price_adjustment: "raw" | "forward" | "backward" | null;
  source_kind: "verified_snapshot" | "normalized_financial" | "vendor";
  evidence_ref_ids: string[];
  committed_sequence: number;
}
```

单位/万/亿换算必须在生成 `normalized_value` 时显式完成并保留原始 artifact 引用；Validator 不根据自然语言猜 scale。

### 10.2 canonical 事实选择与期间规则

1. 只接受 `committed_sequence <= brief.source_sequence` 且引用可解析的事实。
2. 同一 metric/date 的来源优先级固定为 `verified_snapshot > normalized_financial > vendor`。同级不同值按 10.3 的同一数量级/相对误差算法两两比较：差异 `<=1%` 视为展示舍入等价，并选 lexicographically smallest `fact_id`；差异 `>1%` 生成一个包含全部同级 fact IDs 的 `cross_source` conflict，severity 取所有 pair 的最高等级，不选择 canonical fact，依赖它的派生检查记为 `skipped/canonical_source_conflict`。
3. 市值检查要求 price 与 shares currency/单位兼容，shares 的 `as_of` 不晚于 price date，并是该日有效的最近值。
4. PB 使用不晚于 price date 的最近一期期末 shareholders equity；UI 必须同时显示该报告期。
5. PE 只使用 period_end 不晚于 price date、覆盖连续 12 个月的 TTM net income。
6. 不同 currency 只有在 run 已捕获同日 FX rate 和引用时才能换算；否则检查 `skipped=currency_mismatch`。
7. 复权口径不一致时不计算市值；市值必须使用 raw price。
8. denominator 为 0 或负数时 PE/PB 标记 `not_meaningful`；若报告仍宣称普通正倍数，产生 high conflict。

### 10.3 算法、容差与冲突类型

所有运算使用十进制 Decimal：

```text
market_cap = raw_price × shares_outstanding
PB = market_cap ÷ shareholders_equity
PE = market_cap ÷ ttm_net_income
```

令 `D=declared`、`C=computed`。比较顺序固定如下：

1. `D == 0 && C == 0`：pass。
2. 恰有一个为 0：critical conflict。
3. `sign(D) != sign(C)`：critical conflict。
4. 两者非零且同号时令 `MAX=max(abs(D),abs(C))`、`MIN=min(abs(D),abs(C))`。
5. 用交叉乘法判断 `MAX >= 10 × MIN`（含精确 10× 边界）：critical conflict。
6. 否则令 `DELTA=abs(D-C)`，用交叉乘法比较：
   - `DELTA × 100 <= abs(C)`：pass，容纳 1% 展示舍入；
   - `DELTA × 10 <= abs(C)`：medium conflict；
   - `DELTA × 10 > abs(C)`：high conflict。

最后一项等价于 `DELTA × 10 > abs(C)`。严重度判断全程只使用 Decimal 乘法/比较，不受除法 context 影响。`relative_error` 仅作为输出字段，在判级后以 Decimal precision=28、`ROUND_HALF_EVEN` 计算并序列化为字符串。进入比较前不做展示舍入。`70.8 × 50,000,000` 的 C 为 `3,540,000,000`，声明 D 为 `354,000,000`，满足 `MAX = 10 × MIN`，因此是 critical；其 90% relative error 不会覆盖先执行的数量级规则。

类型：

```ts
interface ConsistencyConflictV1 {
  conflict_id: string;
  check: "market_cap" | "pb" | "pe" | "cross_source" | "period" | "currency";
  severity: "medium" | "high" | "critical";
  status: "failed" | "not_meaningful";
  message_code: string;
  declared_fact_ids: string[];
  computed_value: string | null;
  relative_error: string | null;
  evidence_ref_ids: string[];
}

interface DataQualityV1 {
  level: "healthy" | "limited" | "conflicted" | "unknown";
  degraded_capabilities: string[];
  unavailable_capabilities: string[];
  conflicts: ConsistencyConflictV1[];
  checks: Array<{
    check: "market_cap" | "pb" | "pe";
    status: "passed" | "failed" | "skipped" | "not_meaningful";
    reason_code: string | null;
  }>;
}
```

等级映射：存在 high/critical conflict 为 `conflicted`；没有 high/critical、但有降级/不可用/medium/skipped/not_meaningful 为 `limited`；所有适用核心检查通过且无降级为 `healthy`；全部核心检查均因缺少结构化事实而 skipped 时为 `unknown`。因此 denominator 非正、又没有错误正倍数 claim 的 PE/PB 场景确定为 `limited`。

### 10.4 失败语义

- 一致性检查发现冲突：run 仍可 completed，但 brief 标记 `limited/conflicted`，冲突数字不得作为无保留事实进入摘要。
- ReaderBrief 生成失败：不回滚 canonical reports，不把成功 run 改成 failed；UI 回退到原始 Portfolio 入口。
- 证据覆盖通过：显示“身份与证据覆盖通过”。
- 算术和跨报告一致性也通过后，才可显示更强的“关键事实一致性检查通过”。
- 指定案例 `70.8 × 50,000,000` 应算得 `3,540,000,000`，与声明的 `354,000,000` 相差 10×，必须输出 critical `market_cap` conflict。

### 10.5 过程话语隔离

- 模型过程话语保留在 model response/turn artifact。
- 用户报告投影只使用结构化业务字段。
- 禁止用字符串黑名单作为唯一清洗方案；根本边界应是结构化输出与独立审计存储。

## 11. 组件与职责边界

实现拆分为以下可独立理解和测试的单元：

| 单元 | 职责 | 依赖 | 不负责 |
|---|---|---|---|
| `RunProjectionPublisher` | 唯一 writer；持锁、原子发布 brief/view、处理重建 | per-run lock + 两个纯构建器 | Agent 决策、UI 渲染 |
| `ReaderBriefPublisher` | 纯构建器：从四类公共 typed 输出和 DataQuality 构建 brief | committed run facts + evidence refs | 自行落盘、另取锁、修改报告 |
| `RunViewProjector` | 纯构建器：生成轻量视图并绑定 source sequence | events/snapshot/brief | 自行落盘、取代事件真相 |
| `RecentRunsProjection` | 按产品规则过滤、排序、分页 | RunSummary | 删除或重写 run |
| `RunViewCache` | 有界缓存、watermark、取消与去重 | view/artifact API | 推断业务结论 |
| `DecisionBrief` | 渲染 L1 首屏摘要 | ReaderBriefV1 | 读取完整审计 artifact |
| `ResearchEvidenceCards` | 渲染 L2 主题卡 | analyst card projection | 默认挂载全文 |
| `DebateDigest` | 渲染 L3 共识/分歧/变化 | debate digest | 展开所有轮次 |
| `AuditReader` | 按需显示 L4 详情 | artifacts/turns/tools | 改写事实 |
| `OrthogonalWorkflowMap` | 阶段主干与局部正交线路 | workflow projection | 自由曲线路由 |
| `ResizableInspector` | 桌面 resize、键盘、持久化、窄屏抽屉 | layout preference | 业务审计内容 |

## 12. 迁移与实施顺序

### Phase 0：冻结基线与增加度量

- 固化指定 run 作为性能/阅读 fixture，敏感信息仍按现有规则脱敏。
- 记录当前请求数、事件重放数、DOM 数量、切换耗时和长任务。
- 为现有完整报告和失败 run 可访问性增加回归测试。

### Phase 1：先修复切换放大

- 修正历史终态误 refresh。
- 修正 MarketChart 对全局 sequence 的依赖。
- 引入请求取消。
- 切换时立即显示目标骨架并撤下旧内容。
- 运行列表不再扫描全部事件日志。

此阶段不等待新报告 UI，即可显著降低卡顿。

### Phase 2：轻量历史投影和缓存

- 实现 `RunViewProjectionV1` 和 `/view`。
- 历史 terminal run 从 view watermark 增量连接。
- 加入 per-run LRU projection cache 和 artifact 请求去重。
- 拆分 Context 订阅边界。

### Phase 3：读者摘要

- 按 5.3 节持久化 Research、Trader、Risk 和 Portfolio 的 V1 公共 typed artifacts。
- 发布 `ReaderBriefV1` artifact。
- 实现 30 秒首屏和 L2/L3 投影。
- 完整报告、讨论和审计改为按需挂载。
- 按 5.7 节为旧 run 提供 `legacy_fallback`，不从 Markdown 回填。

### Phase 4：工作流与 Inspector

- 替换自由 Bézier 为阶段主干 + 局部正交路由。
- 绑定真实箭头。
- 实现可调整 Inspector 和窄屏抽屉。

### Phase 5：一致性保护与收尾

- 增加确定性财务计算和冲突检查。
- 完成埋点、性能预算、视觉回归和可访问性验收。
- 更新用户文档和旧设计状态。

## 13. 测试策略

### 13.1 后端单元测试

#### ReaderBrief

- 四类 V1 公共 typed artifacts 按 5.2 映射，无跨源猜测。
- 研究评级与执行动作分离。
- top drivers 保留方向、重要度和引用。
- catalysts/invalidation 缺失时进入 omissions，而不是从正文补写。
- Research/Risk/Portfolio reader fields 区分 null、合法空数组和有内容三种状态。
- 每个 PublicClaim 至少一个同 run、已 committed、可解析 ref。
- 模型返回未在 allowlist 的 ref ID 时拒绝该 claim。
- ref resolver 覆盖 artifact/turn/evidence_item/data_call 和 404/409/410。
- target_missing 保留 claim 并显示来源不可用；structural ref error 才使构建失败。
- 降级/不可用/冲突数据进入正确字段。
- 缺失 typed decision 时返回明确不可用状态，不猜 Markdown。
- source sequence 不匹配时拒绝陈旧投影。

#### Recent runs

- 无参数旧 API 保持兼容。
- `view=recent` 排除 failed。
- completed/running/created/cancel_requested/cancelled/interrupted 仍可见。
- failed run 仍可按 ID 获取并 retry。
- 过滤发生在分页前，failed 不占 limit。
- `created_at DESC, run_id DESC` 稳定，cursor 链无重复。
- limit、损坏 cursor、跨 filter cursor 返回规定错误。
- live item 变 failed 后 recent 移除，但当前主视图仍可按 ID 读取。

#### Run view

- 可由事件真相重建。
- watermark 与 snapshot 一致。
- GET view 后、SSE 连接前追加事件不会丢失。
- candidate/output-ready 不进入 committed view。
- applied events 按 250ms 合并，终态强制 flush。
- terminal view 不需要从 0 回放。
- terminal、failed、cancelled、interrupted 的 envelope 状态正确。
- legacy-without-brief 返回 legacy_fallback。
- 投影损坏时可重建，不污染 events；重建失败返回 unavailable shell。
- unsupported schema 不覆盖未知版本文件。

#### 一致性检查

- `70.8 × 50,000,000 = 3,540,000,000`，错误的 `354,000,000` 必须被识别。
- 1%、10%、10× 边界的 severity 精确。
- PE/PB 使用相同币种与期间；currency/period 不兼容时 skipped。
- 0/负 denominator 返回 not_meaningful。
- 同级 canonical 来源冲突不任意选值。
- cross_source pair 使用同一 1%/10%/10× 边界并取最高 severity；`<=1%` 以最小 fact_id 稳定选值。
- 冲突不让 run 生命周期误变 failed。

### 13.2 前端单元/组件测试

#### 默认阅读

- 成功 run 默认只挂载 DecisionBrief。
- 完整报告、讨论、Prompt 和工具内容未展开时不发请求。
- 点击证据引用打开正确上下文，而不是向下追加全文。
- 旧 run 显示诚实降级。

#### 最近运行

- failed 不显示。
- 当前 run 刚失败后主错误面板仍存在。
- RunHistory 不因每个 SSE event 重渲染。
- 快速 A/B/A 只保留最后一次选择的内容。

#### Inspector

- pointer drag、clamp、pointer capture 和松手提交。
- Arrow/Home/End、双击复位、ARIA value。
- 持久化恢复并重新 clamp。
- 窄屏切抽屉。

#### 工作流

- 路径存在 marker-end。
- 只生成允许的正交段。
- active/completed 不改变几何。
- 窄屏显示 stepper。

### 13.3 集成与 E2E

固定 fixture 矩阵：

| Fixture | 用途 |
|---|---|
| live-running | partial view、增量 SSE、状态推进 |
| completed-large-A | 1,313 events、135,120-byte report、冷启动 |
| completed-large-B | 至少 1,000 events、100 KB report、A/B/A |
| failed | recent 隐藏、主错误、retry |
| cancelled | recent 保留、终态 view |
| interrupted | recent 保留、resume/审计 |
| legacy-without-brief | legacy_fallback |
| corrupt-view | 确定性重建 |
| projection-generation-failure | unavailable shell，不污染 run status |

执行：

1. 连续 A/B/A 切换 10 次。
2. 断言选中反馈、摘要可读时间和请求取消。
3. 断言 terminal run 不重新全量回放。
4. 断言 market-view 请求预算。
5. 断言默认页面不存在完整报告正文和逐轮原文。
6. 展开 L2、L3、L4 后验证引用、独立滚动和关闭返回位置。
7. 拖动 Inspector 到最小、最大、刷新恢复。
8. 在宽屏、中屏、窄屏做截图回归。
9. 检查键盘导航和屏幕阅读器语义。
10. 验证 failed 不在最近运行，但可直接访问和 retry。
11. 按 9.4 节执行 3 次预热 + 30 次测量并输出 p95 和原始样本。
12. 使用锁定在 `frontend/package-lock.json` 的 `@axe-core/playwright` 检查 splitter、drawer、tabs 和 evidence links；不允许不同环境替换 runner 后沿用同一基线。

### 13.4 人工阅读验收

给未参与开发的读者查看指定 run，要求在 30 秒内回答：

- 评级是什么？
- 系统实际建议执行什么？
- 最重要的三条理由是什么？
- 最大风险和数据缺口是什么？
- 下一验证节点是什么？

若需要向下滚动整篇报告或打开高级审计才能回答，则 L1 失败。

## 14. 验收标准

### 14.1 产品

- 打开 completed run 首屏是 30 秒摘要，不是完整拼接报告。
- Sentiment、News 和其他 Agent 全文不在默认正文连续铺开。
- 中间讨论完整保留，但只在用户请求时读取。
- 报告评级与执行动作明确分开。
- failed run 不出现在“最近运行”。

### 14.2 视觉与交互

- 工作流主方向通过直线和箭头一眼可见。
- 不出现自由弯曲、回绕、穿卡或无箭头线路。
- Inspector 可鼠标拖动、键盘调整、双击复位并记住宽度。
- 窄屏使用抽屉/stepper，无横向挤压。

### 14.3 性能

- 满足第 9.3 节预算。
- 历史 terminal run 不从 0 重放 1,313 个事件。
- 默认摘要不解析 135 KB 完整 Markdown。
- 快速切换不残留旧 run 内容和请求。

### 14.4 真实性

- 原始事件、报告和 artifacts 未删除、未重写。
- 摘要结论可以定位到证据。
- 数据受限和冲突不会被成功状态掩盖。
- failed run 仍可审计和 retry。
- Evidence PASS 不再误导为“全部事实已验证”。

## 15. 明确禁止的实现捷径

- 仅把曲线改成另一种 Bézier，仍让线路自由穿行。
- 只给 RunHistory 加 `React.memo`，但保留全量重放和请求风暴。
- 只在前端 `filter(status !== 'failed')`，却不定义服务端 recent 投影和分页契约。
- 删除 failed run 文件以实现“不显示”。
- 用完整报告前 320 字作为摘要。
- 新增一个额外 LLM 调用总结现有报告。
- 从 Markdown 标题、英文角色名或自然语言正则推断业务结构。
- 默认挂载内容后再用 CSS 隐藏。
- 在每个 pointermove 更新 React 全局状态。
- 把 `Underweight` 直接显示成“已减仓”。
- 把 `completed` 显示成“所有事实已验证”。

## 16. 工程完成定义

只有同时满足以下条件，才能声明本优化完成：

1. ReaderBrief 与 RunView 具有版本化契约和重建测试。
2. 默认阅读、完整过程和高级审计边界清晰。
3. 指定大 run 满足切换与请求预算。
4. 工作流箭头、正交路由、响应式和视觉回归通过。
5. Inspector 拖动、键盘、持久化和窄屏行为通过。
6. failed 从最近运行移除，但审计与 retry 保持。
7. 报告评级、执行动作、数据质量和一致性状态分别呈现。
8. 所有原始运行事实仍可回放和审计。
9. 自动化测试和 30 秒人工阅读验收均通过。
