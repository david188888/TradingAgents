# 外部工程诊断核查：TradingAgents

- **Status: Historical**
- 核查日期：2026-10-14（Asia/Shanghai）。
- **Do not use this document as evidence of current implementation behavior.**
- 现役答案见[文档索引](../README.md)、[系统架构](../../ARCHITECTURE.md)与[统一研究契约](../contracts/unified-company-research.md)。
- 输入：用户提供的外部 `plan.md`，分五层诊断；未提供其核查 commit、实测日志或性能数据。文中建议是待评估材料，不是实施授权。
- 核查基线：本地 `main`，HEAD `6c50b8bf3e9cb3a80f3de902a07ee8fa06216975`，含既有 ChatGPT/sidebar 未提交改动。结论来自当时工作树，不等同于该 commit 的纯净快照或已部署版本。
- 方法：主 Agent 与三个只读 subagent 分别核查内核、数据、Web/前端；局部合成测试与最小复现，不调用真实模型、不刷新研究数据、不修改历史记录。

## 第一性原理：先定义要保护什么

目标是让 A 股研究者获得可复核的公司判断：能找到原始依据，知道缺了什么，区分已知事实、推断与尚未完成的研究。衡量优化的首要标准是事实可信度与缺口可见性，其次才是时延、模型费用和页面性能。模型成功返回 JSON、执行完成或报告可读，都不能单独证明研究正确。

本次保留以下不变量：

1. 原始资料必须经过下载、解析、单位/时点资格校验、事实准入，才能进入专项和最终报告。
2. 冻结后不能自由取数；专项只能引用自己的合法事实，不能读取其他专项草稿。公共公司背景不扩大引用权限。
3. 确定性计算由代码执行；计算通过不证明经济因果、持续性或合理价值。
4. 恢复保留原身份、输入、提示和已花预算；未知已发出的请求不自动重放。
5. 取消、整轮截止、持久化或 checkpoint 冲突仍是生命周期失败，不能被通用降级吞掉。
6. Reader/Markdown 展示同一已保存记录，不能阅读时补数据、改历史或把模型观点转为已执行验证。

现役链路是 Web → `NativeRunner` → `MinimumEvidenceSources` → 冻结事实 → 经营/事件/市场专项 → 挑战 → 代码核查 → 定向回应 → 综合 → 持久发布 → Reader。classic 与 catalyst 是有兼容消费者的旧路径，不能把旧路径的症状直接归于这条主链。

## 逐项核查原诊断

下表的“不成立”指当前维护路径；“未证实”不表示风险绝不存在。文件链接指向权威实现，行号是本次快照的定位提示。

| 原诊断 | 判断 | 当前证据与含义 |
| --- | --- | --- |
| NativeRunner 正则截取 JSON，固定重试两次，被 CoT 大括号干扰 | 不成立；字符串内嵌 reasoning 是待评估边界 | 解析在 [native_model.py](../../tradingagents/execution/native_model.py) 288–306 行，严格 `json.loads`、重复键拒绝和 schema 验证，没有正则截取。[base_client.py](../../tradingagents/llm_clients/base_client.py) 6–22 行已处理 typed reasoning blocks；内嵌 `<think>` 字符串没有单独剥离，但会严格解析失败。无真实 DeepSeek 截断样本。 |
| `MAX_SUPPLEMENT_ROUNDS = 3` 导致补充后重复跑全专项 | 不成立 | 没有该符号。[catalyst_evidence_policy.py](../../tradingagents/research/catalyst_evidence_policy.py) 93–94 行是最多一轮、三项能力；[native_sources.py](../../tradingagents/dataflows/native_sources.py) 329–340 行先收集/冻结，再启动专项。V7 定向回应也不增加取数或第二轮挑战。 |
| 新旧双轨应直接删 `trading_graph.py` | 共存成立；删除不宜作为当前修复 | [manager.py](../../tradingagents/web/manager.py) 1424–1444 行按 profile 路由兼容 runner；经典执行是 [runner.py](../../tradingagents/execution/runner.py)，不是原文 `analysis_runner.py`。保留历史恢复及程序接口有实际用途。删除必须先做消费者、持久数据和迁移合同审计。 |
| 单专项失败会击穿整次 Run，应加隔离和独立超时 | 部分成立 | [native_research.py](../../tradingagents/graph/native_research.py) 104–110 行已有一般异常隔离；无输出专项标 unavailable，限置信度。242–246 行 `future.result()` 没有角色期限；[native_model.py](../../tradingagents/execution/native_model.py) 493–496 行单请求使用整轮剩余时间。整轮 TimeoutError 明确传播。 |
| 静态 `slice_role_views` 会丢行业 KPI | 行业结构化覆盖不足成立；指定切片丢失未证实 | 没有 `slice_role_views`；现役 [native_policy.py](../../tradingagents/research/native_policy.py) 43–70 行按来源族分配事实。更早的采集/准入只涵盖六类核心财务字段，见 [native_sources.py](../../tradingagents/dataflows/native_sources.py) 68–71 行及 [_verification_plan.py](../../tradingagents/agents/schemas/_verification_plan.py) 18–22 行。PDF已有部分分行业/产品/地区/分部行，但不是完整银行/SaaS指标合同。未发现“已有 NIM/ARR 被切片丢弃”的案例。 |
| 基本面与行情仍靠 LLM 做计算器 | 整体不成立；算子覆盖不足部分成立 | [price_statistics.py](../../tradingagents/research/price_statistics.py)、[record_assembly.py](../../tradingagents/research/record_assembly.py) 120–150 行已有波动率、回撤、VaR/ES、ATR等准入；[native_valuation.py](../../tradingagents/research/native_valuation.py)和[valuation.py](../../tradingagents/research/valuation.py)已有确定性估值链；[minimum_evidence.py](../../tradingagents/research/minimum_evidence.py)已有局部财务核查。不能说 ROIC、FCF yield、杜邦拆解都已供 native 专项使用；也不能把仓库中通用 metric engine 的存在当作 native 已接入。 |
| Pydantic 只能验字段类型，不能发现数值幻觉 | 数值语义缺口成立；“只查类型”不准确 | [_native_stage.py](../../tradingagents/agents/schemas/_native_stage.py) 33–47、90–96 行还验证失效条件、重复引用和证据归属；[研究记录 schema](../../tradingagents/agents/schemas/_research_record.py)校验快照、资格、时点、维度及重算检查。但自由文本中的数字不逐个与引用事实对齐，见下方复现。 |
| Bocha 仅基础正则清洗，同质化通稿稀释 evidence_v1 | 兼容链部分成立；V7归因不成立 | 原文三个 `*DataFlow`/`*Flow` 类不存在。V7选官方公告链，[native_sources.py](../../tradingagents/dataflows/native_sources.py) 49–60 行默认 sources 不含 Bocha。[news_curator.py](../../tradingagents/dataflows/news_curator.py)已有兼容新闻去重/过期过滤；Bocha摘要直接保留而非此处正则清洗，可残留HTML/实体，模糊标题去重还可能合并数字不同的新闻，见下方。 |
| fallback 未归一单位、百分比和复权 | 全盘缺失不成立；逐能力核验仍有价值 | [native_qualification.py](../../tradingagents/dataflows/native_qualification.py)与[tushare_price_history.py](../../tradingagents/dataflows/tushare_price_history.py)保存货币、价格单位、复权和PIT来源；历史复权 vintage 未验证会拒绝准入。[CapabilityResultV1](../../tradingagents/dataflows/capability_result.py)是可用性/尝试语义，不是每个数据字段的完整单位容器。未复现现役 fallback 量级错误。 |
| 全局没有 Point-in-Time 契约，历史评估会泄露未来数据 | 不成立；完整历史vintage尚未证明 | [CapabilityResultV1](../../tradingagents/dataflows/capability_result.py) 99–148 行已有 cutoff、publication/filing、observed、fetched时点；冻结与价格/披露资格另有准入检查。价格因子、估值等无法证明历史vintage时明确不可用；财务披露日期及更新时间过滤不等同于完整历史修订档案，本次未证明所有历史来源均具备PIT vintage。 |
| LocalLedgerStore 无锁，并发专项写坏 JSONL | 当前维护入口不成立；多写入者边界存在 | 实际类是 [RunStore](../../tradingagents/runtime/store.py)，75–87、163–211 行有 per-run RLock、连续sequence、完整行追加和fsync；checkpoint journal也有锁。锁不跨独立实例/进程共享。默认 [web/cli.py](../../tradingagents/web/cli.py) 77–81 行单进程，不能把跨进程风险描述为已发生专项竞态。 |
| SSE无序号、Last-Event-ID和历史回放 | 不成立 | [api.py](../../tradingagents/web/api.py) 815–855 行已有 `/api/runs/{run_id}/events`、两种游标及 `id: sequence`；[broker.py](../../tradingagents/web/broker.py) 177–229 行已有同锁持久化、watermark、磁盘到实时原子交接。不是原文 `/api/research/stream`。 |
| ReportReader/EvidenceInspector仅单向阅读 | 主前提过期；自动关联仍可增强 | 两个组件名不存在。当前 [NativeReader](../../frontend/src/components/reader/NativeReader.tsx)、[ReaderEvidence](../../frontend/src/components/reader/ReaderEvidence.tsx)、[InvestmentJudgement](../../frontend/src/components/reader/InvestmentJudgement.tsx)已有依据点击、保存来源/字段、专项归属、挑战→核查→回应→裁决。点击一个主张后右侧尚不同时自动列出其全部攻防；可以先验证该小范围联动需求。 |
| 多轮补充/长日志未虚拟化已导致DOM和FPS瓶颈 | 未证实 | 现役无原文三轮补充；Reader切换view、证据选择和角色详情均有条件挂载。完整记录和目录仍全量渲染，潜在规模风险存在；无CPU、长任务、DOM或FPS测量，不足以证明必须先上虚拟滚动。 |
| 前端无指数退避与序号幂等，需新增 | 不成立 | [useRunStream.ts](../../frontend/src/hooks/useRunStream.ts) 36–44、98、119–128、179–191 行已有退避、有限重连、游标恢复及刷新回放；[runReducer.ts](../../frontend/src/state/runReducer.ts) 211–224 行丢弃重复序号。fetch流使用正文sequence，忽略 `id:` 行不等于没有恢复。 |

## 三个可复核的边界

### 1. 合法引用可以携带错误的自然语言数字

本地主 Agent 独立复现与 subagent 结果一致：

```python
from tradingagents.agents.schemas._native_stage import (
    HypothesisProposalV1, validate_hypothesis_references,
)

fact = {"id": "fact.growth", "statement": "营收同比增长18.4%",
        "evidence_ids": ("evidence.growth",)}
proposal = HypothesisProposalV1.model_validate({
    "statement": "营收同比增长25%，增长质量较好",
    "supporting_fact_ids": [fact["id"]],
    "conditions": [{"condition_role": "invalidation",
                    "text": "下一期营收增速显著下降", "check": None}],
    "alternative_explanation": "增长可能由低基数造成",
})
validate_hypothesis_references(proposal, {fact["id"]: fact["evidence_ids"]}, {})
# schema 与引用校验均通过；自由文本数值没有进入此门禁。
```

这证明门禁边界，不是证明某份真实模型研究已经出现此错误，也不是完整发布链E2E结果。正确引用ID只是必要条件。

候选设计：先支持有限的结构化数值声明，绑定事实/字段、报告期、合并口径、单位与复制/计算类型。复制数字直接匹配原值；衍生数字引用代码计算的结果及版本。文本由已验证数值渲染或限定模板生成。只用正则抽取全文数字、给一个统一误差阈值，无法区分“25%目标”与“18.4%历史值”、百分比与百分点、同比与环比、估计值与实际值。拒绝/降级与旧记录兼容仍需用户确认后的合同设计。

### 2. 一般专项异常与整轮超时是不同控制路径

subagent 对同一合成 facts-only seed 注入调用异常：`RuntimeError` 会降级该专项并产生 partial/LOW_CONFIDENCE；`TimeoutError` 直接传播，后续综合不执行。此最小seed仅含一个专项，不是兄弟专项交付实测；一般异常隔离与后续固定顺序合并另有代码和局部测试支持。专项独立时限尚未实现，但“所有失败都无隔离”不准确。

若增加角色时限，应使用独立的角色超时类型，记录角色不可用，并验证已完成兄弟结果如何交付；整轮截止、取消和checkpoint冲突必须继续传播。线程 `future.result(timeout=...)` 只能停止等待，不能保证中止HTTP请求；SDK取消/超时、预算结算、持久结果和晚到响应都需一起处理。不能简单catch所有TimeoutError后继续。

### 3. 兼容新闻模糊去重可能丢掉数值冲突

subagent用同日、不同URL的“甲公司2026半年报营收增长15%”与“甲公司2026半年报营收增长25%”输入兼容新闻去重（显式启用默认模糊参数：阈值0.5、两天窗口、最少5个重叠bigram），结果只剩一条，保留数字随输入顺序变化。这证明相近标题可吞掉数字差异；未证明现役V7研究受影响。算法未确认数字或修订关系，不能将另一条直接丢弃归于合法版本更新。处理原则应保留数值/时间/否定/修订差异与全部原始出处，再考虑事件聚类。复现入口为 `news_curator._dedupe_news_items`，368–423、463–485 行。

V7使用另一条确定性去重路径：[catalyst_events.py](../../tradingagents/dataflows/catalyst_events.py) 261–289 行的key包含证券、公告ID、发布时间和内容指纹；数字变化不会被该指纹正常化抹掉。[minimum_sources.py](../../tradingagents/dataflows/minimum_sources.py)按公告ID整理目录；机构预测按机构/年份选最新是显式版本规则。不能把兼容新闻复现推广到V7。

## 对优化建议的取舍

| 建议 | 本次判断与后续条件 |
| --- | --- |
| 原生 JSON Schema / Tool Calling | 可做供应商能力分级实验；当前native `.invoke(prompt)`尚未启用强结构输出。能力表和配置不等于真实服务已支持，需每provider/model/task核验，保留严格引用和发布门禁。 |
| 剥离 reasoning 与用 json-repair 自动闭合 | typed reasoning已有处理。可以针对已知协议验证内容分离；不建议自动补全截断输出后当作研究结果，语法可修不等于缺失结论有证据。 |
| 增量局部重算 | 原文循环前提不存在，当前无实施理由；若以后引入新增证据，先定义新快照、依赖图、失效范围与衍生版本。 |
| 独立角色时限/降级 | 候选改动，需要设计与慢调用测量；不能削弱整轮deadline等不变量，也不能捏造数值置信度扣分。 |
| 删除兼容图 | 不执行。保留真实兼容需求；独立迁移另行审计。 |
| 大量新增 ROIC/FCF/杜邦/波动率锥等算子 | 先按研究问题核验必要输入与可得性，复用现有确定性链。不能先加公式再补未经资格验证的字段。 |
| skills Markdown/YAML 动态挂载行业证据 | 不按原样采用。[registry.py](../../tradingagents/skills/registry.py) 1–6、32–34、48–50 行限定方法论prompt和code-owned角色/选择边界。行业字段、单位、PIT、来源资格和角色权限应先由代码合同定义；Markdown仅解释方法论。 |
| 数值引用校验器 | 值得优先设计；使用上文有限结构化锚点，避免全文模糊误差比较和无限重试。 |
| 每个数字都在 CapabilityResult 内带单位/时间 | 不宜统一堆入可用性envelope。逐能力payload/数值模型表达字段口径，结果层保留source、cutoff与尝试轨迹；先找具体出口缺口再改合同。 |
| 新闻语义去重+小模型压缩 | V7官方资料先保证原文和冲突保留。兼容链已有去重且存在误合并风险；模型摘要应是派生物，不能替代事实或静默增加调用预算。 |
| 全局HTTP装饰器、令牌桶、SQLite TTL | 已有 [BudgetedSession](../../tradingagents/dataflows/catalyst_transport.py) 17–61 行的统一native HTTP边界：全局两并发、逐请求预算、取消与剩余deadline裁剪、显式零自动重试；[native_runner.py](../../tradingagents/execution/native_runner.py) 223–265 行已有run内结果复用与未知dispatch防重放。供应商局部timeout仍存在，但不是没有公共边界。先列逐源请求矩阵；新增retry/跨run缓存会改变预算、恢复和PIT语义。SQLite不是本次已证明需要的组件。 |
| SSE重放与锁 | 已实现，无需重复建设。补充现有同Store实例/单进程边界文档。 |
| 三栏联动与虚拟滚动 | 先在现有Reader验证“点击主张同时展示相关攻防”的具体收益；虚拟滚动待长记录实测再选择，不预设三栏。 |
| 人工暂停、编辑假设后恢复 | 是新产品语义，不是健壮性小修。现役V7不是固定13节点，run状态无人工审核暂停；现有resume用于interrupted原checkpoint。需要审核状态、人类修改归属、审计记录、衍生版本和受影响挑战/回应/综合的重算设计，不能覆写原假设继续原身份。 |

建议顺序：先处理结构化数值声明与已资格验证原值的对齐；再按实际失败/时延证据决定角色期限；行业扩展先选具体A股行业及研究问题，从原始资料、解析、准入做到专项。兼容新闻问题单列低优先级；大规模性能、人工审核和兼容退役均不作为当前缺陷直接实施。

## 验证与知识收尾

本次新增这份调查记录与索引指针；[统一研究契约](../contracts/unified-company-research.md)补充引用校验不等于自由文本数值正确；[可回放运行记录](../operations/observability-replay.md)补充现有SSE/游标/锁边界，并明确重试身份适用于V6/V7；[A股数据能力](../operations/a-share-data-capabilities.md)修正过期的深交所日历优先/三种新建模式概述，指向既有现役日历说明。无行为代码改动，因此不重建前端资产，不覆盖既有构建产物，不改README的能力描述或制造功能发布记录。

| 事实面 | 状态 | 本次依据/限制 |
| --- | --- | --- |
| 代码 | verified-current | 当前工作树、三个分层审计及局部合成测试；不是全仓无缺陷结论。 |
| 运行态 | pending | 8765端口检查未发现监听者；没有启动/重启服务或真实研究，不证明其他端口状态或用户实际页面。 |
| 文档 | changed-and-verified | 只更新上述知识边界、索引与本调查，执行文档门禁和差异检查。 |
| 规则 | verified-current | 全局RTK/Hindsight边界、项目及Python/frontend scoped指南；CLAUDE.md导入AGENTS.md，未新增平行规则。 |
| 记忆 | out-of-scope | Codex生成记忆仅用于定位并以当前代码复核，没有写入；Hindsight没有查询或修改。 |
| 工作区 | verified-current | 机械枚举134个当前checkout Markdown（过滤依赖/构建/嵌套worktree）；记录既有dirty状态和7个worktree，包括主checkout。只盘点，不声称已集成或可删。 |

本地验证：

- 内核：`tests/test_native_model.py`、`test_native_retry.py`、`test_native_specialist_isolation.py`、`test_native_research.py`、`test_native_valuation.py`：147 passed。
- 数据：`test_native_multisource.py`、`test_native_valuation.py`、`test_news_curator_dedup.py`、`test_a_stock_v37.py`、`test_alpha_vantage_hardening.py`、`test_capability_result.py`：123 passed。与内核套件有重叠，不相加宣称唯一测试数量。
- Store/broker/SSE：`tests/web/test_run_store.py`、`test_event_broker.py`、`test_sse.py`：33 passed。
- 前端：eventSource、useRunStream、runReducer、runReducer.gap、InvestmentJudgement、NativeReader.focus：6文件29 passed。
- `ruff check tradingagents cli scripts/check_agent_docs.py`、`python scripts/check_agent_docs.py`与`git diff --check`通过；使用既有Conda tradingagents环境。

上述是局部离线验证，不是全套测试、GitHub CI、真实模型能力、投资研究质量或性能验收。

待决：数值声明新合同、角色期限、具体行业覆盖及人工审核语义均未实施；需要用户选择范围后再设计。未验证的真实服务/研究质量/长记录性能保持pending，付费调用与Git发布out-of-scope。既有ChatGPT/sidebar改动及历史worktree未做内容审计，也没有删除候选资格；复核现场仍保留，本次未清场。
