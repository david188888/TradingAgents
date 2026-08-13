# TradingAgents 第一性原理总体评审

日期：2026-08-13

> 状态：已冻结的审计快照，不是现役产品合同。当前实现状态与路线统一维护在
> [`docs/learning-research-reader.md`](../learning-research-reader.md)。

## 1. 产品目标与非目标

TradingAgents 的目标不是自动赚钱，也不是把多 Agent 包装成量化交易系统。它应当帮助用户：

1. 用稳定、可复核的路径理解一家公司；
2. 把宏观环境、行业结构、公司经营、估值与风险联系起来；
3. 在阅读结论的同时学习分析方法；
4. 即使未来更换模型，证据边界、研究步骤、降级规则和公开输出仍保持一致。

明确排除：自动下单、仓位优化、收益榜、P&L 奖励、跟单、名人投资者 persona、技术买卖点，以及由模型自由决定证据是否充分。

## 2. 第一性原理判断

多 Agent 系统的可靠性不来自“角色更多”或“辩论更激烈”，而来自四个代码拥有的边界：

- **事实边界**：每个公开事实必须指向冻结时点内的 durable evidence 与 coverage；
- **方法边界**：分析镜头、所需能力、公式输入和反证规则必须版本化；
- **不确定性边界**：缺失、不支持、供应商故障、过期、部分覆盖和无数据必须分开；
- **结论边界**：模型可以解释和提出假设，但不能提升 evidence eligibility，也不能绕过 fail-stop/abstain。

因此合理架构是：

```text
AnalysisCutoff
  → policy-owned deterministic prefetch
  → typed capability results + durable evidence registry
  → analyst lenses
  → evidence-bound claims and counterclaims
  → code-owned conflict / eligibility / rating cap
  → learning-oriented Research Case
  → Reader + Audit replay
```

## 3. 本轮已经完成的结构改进

### 3.1 数据与时点

- 新增 `AnalysisCutoffV1`，时敏抓取前冻结市场本地分析日边界；
- 新增 `CapabilityResultV1` / `ProviderAttemptV1`，区分 `available`、`partial`、`not_covered`、`not_supported`、`provider_unavailable` 和 `invalid`；
- 修复 OHLCV 前视填充、默认 global fundamentals 路由、核心 no-data 语义、新闻时区/未知时间、ticker 身份冲突；
- A 股官方披露采用 CNINFO / 交易所 any-of required group，EastMoney 不再冒充交易所官方来源；
- fundamentals、official、identity、snapshot、adjusted price、event window 均形成 typed producer 与 durable bundle。

### 3.2 Registry、claims 与资格

- Evidence Registry 采用 content hash、latest committed selection 和 fail-stop 完整性校验；
- required capability 缺失或不可用会强制 `insufficient_evidence`，并生成代码控制的 unknown / review action；
- Research Manager 只能看到本次运行中真实 available 的 candidate key；
- `claim lens ↔ coverage capability` 由单一代码映射控制，assembler 和 eligibility 双重复验；
- 当前 policy 的 required capability 必须恰有一个 market/date/coverage 一致的 typed result，单独的 legacy complete coverage 不能得到 full；
- typed bundle 存在时禁止再生成同 capability 的 legacy coverage ref。

### 3.3 图、恢复与治理

- required prefetch 已与用户选择的 analyst 解耦；只选择 News Analyst 仍会先完成 required price/event/中长期 fundamentals 生产；
- cutoff 失败时 price、news、fundamentals 对称生成 typed negative result，且不访问 provider；
- runtime semantics hash 纳入 bundled `SKILL.md`，方法论变化会使旧 checkpoint 失效；
- CI 已加入 cutoff、capability、fundamentals、official、Registry、eligibility、六格矩阵与 required-prefetch 图测试。

## 4. 六格策略状态

| 市场 × 周期 | Required 能力 | 当前结论 |
|---|---|---|
| A 股 × short | identity、snapshot、adjusted price、event window | 可条件达到 full |
| Global × short | 同上 | 可条件达到 full |
| A 股 × medium | 基础四项 + official + quarterly fundamentals | 可条件达到 full |
| Global × medium | 基础四项 + SEC + quarterly fundamentals | 当前必然 limited：SEC provider 未实现 |
| A 股 × long | 基础四项 + official + annual fundamentals | 可条件达到 full |
| Global × long | 基础四项 + SEC + annual fundamentals | 当前必然 limited：SEC provider 未实现 |

Global 中长期的 limited 是诚实的产品能力缺口，不应通过放宽规则伪装成 full。

## 5. finance-quant-trading 合集深读

合集：[david188888 / finance-quant-trading](https://github.com/stars/david188888/lists/finance-quant-trading)。审计时共有 9 仓；全部检查 README、目录树、关键入口和核心实现路径，审计快照固定到下列 commit。

| 仓库 / 快照 / 许可 | 架构与价值 | 可迁移机制 | 风险与明确排除 |
|---|---|---|---|
| [Geeksfino/finskills@8722415](https://github.com/Geeksfino/finskills/tree/8722415a68db3250516a8c6f9632da29c1554bf1)，Apache-2.0 | 30 个中美金融 Skills，`SKILL → references → toolkit` 渐进披露；财报、杜邦、盈利质量、Altman、Piotroski、Beneish 等 | 版本化教育型 ResearchLens、财报问题树、来源纪律、报告模板、方法与工具分离 | 阈值常被当作通用标准；A 股脚本有静默异常；缺 cutoff/evidence/freshness。排除选股、组合优化和仓位结论 |
| [TauricResearch/TradingAgents@a33fd4c](https://github.com/TauricResearch/TradingAgents/tree/a33fd4c0f134485a43553a2c23a63cb14adbd88f)，Apache-2.0 | LangGraph 分析师、牛熊辩论、研究经理、交易/风险/组合链 | 继续作为上游同步基线；选择性同步图模块、provider fallback、结构化输出、checkpoint、身份与 no-data 修复 | 大量自然语言和 BUY/HOLD/SELL；经理裁决辩论文本；历史新闻未冻结。排除 trader、执行与 P&L 记忆终点 |
| [virattt/ai-hedge-fund@eff8a73](https://github.com/virattt/ai-hedge-fund/tree/eff8a7320fcf0b473b135690fa1a5b0d9b022a83)，MIT | Fund → strategy → alpha → portfolio → risk → execution；回测/live 共用管线；Financial Datasets API | **最高优先**：filing-date PIT snapshot、内容 hash、CycleRecord、infra fail-loud、证据/LLM失败 abstain | 专有数据；sector/industry latest-only；conviction 单分数过度简化。排除权重优化、回测收益宣传、live execution 和 persona 权威 |
| [ZhuLinsen/daily_stock_analysis@3b98aa1](https://github.com/ZhuLinsen/daily_stock_analysis/tree/3b98aa1d779a3525660b5bd95a2b297278808464)，MIT | FastAPI/React/Desktop；AnalysisContextPack、多策略编排、分歧、风险覆盖、runtime facts、provider trace | 状态词汇、块级质量、确定性冲突摘要、无效意见隔离、代码置信度惩罚、degraded-stage 事件 | 缺统一 cutoff/evidence identity；某些质量分会虚高；交易技术策略过重。排除买卖点和以 P&L 调权 |
| [virattt/dexter@ecaed30](https://github.com/virattt/dexter/tree/ecaed3011f24ea24ef687ab536aa7f22f7294038)，README 称 MIT、仓库无 LICENSE | TypeScript 自主金融研究 Agent；计划、工具、自检、压缩、scratchpad、rubric eval；10-K/10-Q/8-K 分章节 | evidence-gap planner、filing section router、原子 rubric、矛盾检查、原始结果/摘要分离 | TS→Python、专有数据、许可不明确、无全局 cutoff、记忆可污染时效。排除自动目标价/仓位/止损 |
| [HKUDS/AI-Trader@d03ff6c](https://github.com/HKUDS/AI-Trader/tree/d03ff6c056b32ced735adf7c19ed8175adb1c8df)，README 有 MIT 标识、仓库无 LICENSE | Agent 社交交易/跟单平台；不可变实验、挑战、团队、研究导出 | 只借鉴不可变 experiment event、variant ID、匿名研究导出、stable agent hash、verifiability rubric | 许可需澄清；跟单、收益、榜单、奖励会制造从众。全部订单/跟单/声誉奖励排除 |
| [Open-Dev-Society/OpenStock@4597c9a](https://github.com/Open-Dev-Society/OpenStock/tree/4597c9a668118844b588f95eddb9342eed31c41d)，AGPL-3.0 | Next.js/Mongo/Inngest；自选股、公司页、提醒、邮件、情绪卡 | 仅 clean-room 借鉴 watchlist shell、来源覆盖/分歧 UI、研究条件监控、事件后台任务 | AGPL 不直接混入 Apache；provider 错误常退化为 null/0；缺官方披露/cutoff。情绪卡不可作为公司事实 |
| [simonlin1212/a-stock-data@3a3149d](https://github.com/simonlin1212/a-stock-data/tree/3a3149dedbe30cda58b5c94387039d7e707cedcd)，Apache-2.0 | README + 3328 行 SKILL；覆盖 15 类 A 股数据故障域 | 官方公告 fallback、failure-domain 路由、920xxx 歧义、stale/僵尸报价、invalid ticker/空响应防护、endpoint registry | 应重写为 typed adapter + fixture；非官方接口脆弱且存在关闭 TLS 校验。严禁 SSL bypass；排除热榜/龙虎榜/资金流等交易核心化 |
| [haskaomni/serenity-skill@dedcf8f](https://github.com/haskaomni/serenity-skill/tree/dedcf8f9ca8bd48f21239456ede50a9eb9f7ecb0)，MIT | 六个研究 Skills；官方财报/IR/交易所优先；区分事实、指引、共识、推断 | **教育目标高度匹配**：新闻→需求→报表传导→公司弹性→验证；一至三阶受益者、反证、证伪、利润池与三阶段区分 | Bayesian/GF-DMA/TAM-PEG 阈值是启发式，必须版本化并标注假设。排除 Buy/Sell/仓位和伪精确概率 |

## 6. 外部机制的迁移顺序

1. **ai-hedge-fund**：把当前 capability bundles 收束为统一 `PointInTimeEvidenceSnapshot`；
2. **daily_stock_analysis**：补 `ConflictSummary`、块级质量和确定性 confidence cap；
3. **serenity-skill + finskills**：建设教育型 `ResearchLensResult` 与 `LearningTrace`；
4. **a-stock-data**：继续强化 A 股公司身份、官方公告、财报、历史行情四类 failure-domain；
5. **Dexter**：证据契约稳定后再加入 evidence-gap planner、自检和原子 rubric。

推荐长期核心契约：

```text
PointInTimeEvidenceSnapshot
  cutoff, identity, evidence_items, source/result IDs,
  published/accepted time, availability, freshness,
  missing_reason, content_hash

ResearchLensResult
  lens_id/version, questions, hypotheses,
  evidence_refs, counterevidence_refs,
  unknowns, assumptions, monitoring_indicators,
  confidence_rationale

ConflictSummary
  claim_conflicts, source_conflicts,
  missing_core_evidence, degraded_stages,
  deterministic confidence cap/penalty

LearningTrace
  why_this_metric, formula_inputs,
  source, uncertainty, falsification_condition
```

## 7. 剩余路线图

### P0

1. 实现 global `sec.company_filings` 的 submissions/filings、accepted timestamp、分页 coverage 和 cutoff；
2. 把 A 股 `verified_identity` 从“交易所后缀正确”收紧到公司名称、证券类型与上市状态可验证；
3. 让真实生产 e2e fixture 发布 `research-case-v2` 与 typed capability audit，而不是旧 public output 模板。

### P1

1. 将一次运行的 bundles 聚合为统一 PIT snapshot；
2. 新增代码化 claim/source conflict 与 confidence cap；
3. 为每个 ResearchLens 提供问题、解释、公式输入、反证、监测指标与版本；
4. 新闻继续从 Markdown 迁移到结构化 `NewsItem`，保留 vendor、publisher、published_at、artifact 和 event cluster；
5. 使用交易日历替代当前 snapshot freshness 的周末容忍近似。

### P2

1. 引入 evidence-gap planner 和按 filing section 检索；
2. 建立原子化 rubric：引用真实性、时点一致性、反证覆盖、未知项完整性、学习解释质量；
3. 增加 deterministic benchmark，而不是以投资收益衡量模型优劣。

## 8. 验证结果

- 关键后端门禁：122 passed；
- 全仓后端：1713 passed，剩余失败来自旧契约断言、live 网络/Wind 环境、本地旧 UI/图拓扑断言；
- 前端 typecheck：通过；
- Reader/Audit 相关前端测试：通过；完整前端套件的 2 个失败来自工作树中预先存在、未纳入本项目提交的 UI 变更；
- 浏览器实际验收：创建运行、SSE 完成、Reader 安全降级、Audit 打开/刷新、重载与持久化重放均通过，控制台无 warning/error；
- 电脑实际验收：macOS Preview 检查真实页面全页截图与滚动布局；Codex 应用本身因 Computer Use 安全策略不可直接控制。

## 9. 最终判断

本轮之后，TradingAgents 已从“多 Agent 生成交易意见”显著转向“证据约束的学习型公司研究系统”。当前最重要的缺口不是再增加角色，而是 SEC/PIT、严格公司身份、结构化新闻、冲突契约和教育型 ResearchLens。只要继续沿这些代码拥有的边界演进，即使未来更换模型，系统也能保持一致的分析路径和诚实的降级行为。
