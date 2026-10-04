# 上游 v0.6.0 借鉴评估：A 股研究的精简、准确与流程必要性

Status: Historical

后续进展（2026-10-04）：官方 DeepSeek 模型兼容与可选按任务 effort 已完成
实现和验收，当前行为见[推理配置](../../operations/llm-reasoning.md)，检查结果见
[验收记录](2026-10-04-deepseek-task-effort-validation.md)。本文下列未实现／未付费
说明保留为最初评审阶段的快照；日期纠错与 HTML 导出仍是候选建议。

Do not use this document as evidence of current implementation behavior.
This is a review snapshot and proposed triage, not an implementation or migration approval.
Current behavior belongs to [ARCHITECTURE.md](../../../ARCHITECTURE.md) and
[evidence research operations](../../operations/evidence-research.md).

## 评估结论

建议选择性借鉴日期纠错、离线报告的呈现方式与安全渲染、结论归属、调用超时原则。
用户补充了资源约束：保留单一 DeepSeek V4.1 Flash，后续只考虑按任务调整推理 effort；
跨模型/跨供应商对照退出当前计划。自动交易决策结算不适合恢复到当前研究系统。
最直接影响用户目标的本地问题，是已有 `evidence_v1` 仍主要通过 API 创建，普通 CLI
和工作台表单继续采用 classic；更简洁的研究链路尚未成为普通用户直接可选的入口。

优先级以用户能否得到必要、可复核的信息衡量，不以新增功能、agent 数量或报告长度衡量。
这次评估没有证明任何方案提高预测准确率，也没有实施上游修改。

## 范围与证据基线

- 用户在本次评估中明确：当前主要研究 A 股，以
  [a-stock-data](https://github.com/simonlin1212/a-stock-data) 为主要数据能力参考，
  认为当前数据路线足够；考虑 VPN 与市场范围，Yahoo、Alpha Vantage 修复暂不实施。
  这是优先级决定，不是认定 VPN 导致代码缺陷，也不是认定相关缺陷已修复。
- 用户随后确认：使用 DeepSeek 官方 API 与 V4.1 Flash。单模型 effort 策略按官方
  协议评估，不再以第三方网关的参数映射为待决条件。
- 本地：`main`，`f18f7b1`；评估开始时工作区干净。
- 上游：[v0.6.0 发布页](https://github.com/TauricResearch/TradingAgents/releases/tag/v0.6.0)，
  tag 解引用为 `1394a3f72aa4393e1a98f51b382434c4b4c2d972`。
- 发布时间：`2026-10-03T21:30:11Z`，即北京时间 **2026-10-04 05:30:11**。
- 上游 `v0.5.2`：`5eb50854dad299381861632aa34014448b4260fc`。
  `v0.5.2..v0.6.0` 共 25 个提交，包含合并、文档和发布提交；53 个文件发生变化。
- 上游 `v0.5.1`：`35543d0248bf89fcb92b17a15858ad0c0e940687`。
  `v0.5.1..v0.6.0` 共 89 个提交。补读 v0.5.2，是为区分既有功能和 v0.6.0 新变化。
- 本地与上游的 Git 共同祖先为 `9dee508c44662702281a8dbaad1f7b42179b5ba7`。
  本地已有选择性移植，Git 祖先关系不能代表功能尚未借鉴。
- 上游在 `/private/tmp/tradingagents-v060-review-20261004` 独立检出；没有在本地
  `main` 合并、切换分支、改写 refs、commit 或 push。

> 🧠 **From Hindsight memory (证据驱动研究与统一 Reader 重构)** — 已确认的产品方向是研究辅助，采用证据、假设、挑战、核查与综合；优先展示判断、关键依据、最大疑点与下一步，证据按需展开。上述记忆仅用于恢复设计意图，当前实现以下列代码与运行文档为准。

本轮确认的当前边界：

- [native_research.py](../../../tradingagents/graph/native_research.py)：按证据视图运行专项，
  固定顺序汇合，一次挑战，有界工具核查，一次综合；无合格事实的专项不派发。
- [native_model.py](../../../tradingagents/execution/native_model.py)：模型给结构化提议，
  有剩余时间 timeout、禁用 SDK 重试、durable dispatch 与恢复约束。
- [native sources](../../../tradingagents/dataflows/native_sources.py) 与
  [native qualification](../../../tradingagents/dataflows/native_qualification.py)：
  A 股多源按能力准入；保留披露日期、币种/单位、身份、截点与复权资格。
- [native record](../../../tradingagents/research/native_record.py)、
  [publication](../../../tradingagents/execution/native_publication.py)、
  [reports](../../../tradingagents/runtime/reports.py)：发布已校验记录，Markdown 和 Reader 同源。
- [operations](../../operations/evidence-research.md)：`classic` 仍为默认；
  `evidence_v1` 创建需显式 API 请求与独立开关，尚无新增工作台选择器或 CLI profile 选项。

## 从第一性原理定义“有价值”

一次研究应让用户尽快回答：研究问题是什么，判断是什么，哪些事实支持它，
最大反证是什么，下一步查什么才能改变判断。

每个环节必须满足至少一个条件：引入相关新证据、提出可证伪的解释、发现遗漏/反例、
执行能区分解释的核查，或把这些内容整理成可阅读的判断。仅重述上一环节、增加立场、
增加表决次数，不能自动证明该环节必要。

准确性应按四层分开验收：

1. 数据：对象、日期、披露时间、单位、调整口径正确。
2. 主张：事实有原文/来源，推断有引用与适用条件，引用他人意见不成为系统自身结论。
3. 核查：仅把真实执行且有输入版本的检查计为已核查；失败和未解决问题保留。
4. 阅读：首屏不遗漏重大疑点；相同记录的 Reader 与导出报告保持一致。

模型或源数据仍可能出错。工程上的目标是减少错误、让错误可发现、让不确定性显式呈现；
“运行完成”“PASS”与预测结果正确必须分开。

## v0.6.0 的完整主题分流

按 13 个评估主题统计：`take 0 / adapt 4 / defer 7 / reject 2`。
这是建议分类，**没有集成**。`adapt` 不代表一定需要新增代码：已有等价约束的部分应保留，
只有确认缺口才移植。

| 主题与上游依据 | 分类 | 对当前 A 股系统的判断 |
| --- | --- | --- |
| 无效起始日期反馈给模型，`f723824` / [#1476](https://github.com/TauricResearch/TradingAgents/pull/1476) | adapt，高 | 与数据供应商无关。本地会静默把窗口缩成一天；建议显式参数错误，保留截点/身份校验，并在既有额度内允许纠错。 |
| 自包含 HTML 报告，`56a98d9` / [#1419](https://github.com/TauricResearch/TradingAgents/pull/1419) | adapt，中 | 可借鉴离线、手机、打印、目录和安全渲染；从已提交研究记录导出简报。上游依旧展开各 agent 全文，直接移植不能减少信息冗余。 |
| 他人评级与自身结论分开、报告头元信息，`df630b9`、`d53b076`、`460b82e` / [#1466](https://github.com/TauricResearch/TradingAgents/pull/1466) | adapt，原则重要 | 本地已使用结构化 assessment/主张引用，应保留这一结构。借鉴“结论来源明确”，不引入 Buy/Sell 的文本评级解析；导出时显示研究截点、完整性、质量与限制。 |
| Gemini 默认 timeout，`9df071b` / [#1417](https://github.com/TauricResearch/TradingAgents/pull/1417) | adapt，条件性 | native 已传剩余时间 timeout；这里不重复添加 600 秒。若继续使用 classic + Gemini，可补未显式设置时的有限 timeout。 |
| quick/deep 独立供应商与 endpoint，`cc39a35` / [#1440](https://github.com/TauricResearch/TradingAgents/pull/1440) | defer，用户资源约束 | 本轮不引入多模型或多供应商。借鉴按任务分配推理资源的原则，改为官方单一 DeepSeek V4.1 Flash 的 effort 分工；具体策略与预算仍需确定。 |
| Yahoo 搜索新闻备用与 null 字段容错，`4429078`、`9dceea6` | defer，用户已决定 | 本轮暂不实施；不进入建议首批。 |
| Alpha Vantage 拒绝请求与密钥错误文本处理，`5ca37b5`、`97b79e0` | defer，用户已决定 | 本轮暂不实施；不能把未来兼容问题当作当前 A 股主线工作。 |
| Yahoo 金额币种，`810b4cc` / [#1456](https://github.com/TauricResearch/TradingAgents/pull/1456) | defer，市场范围外 | 对海外股票/ADR重要，当前不移植 Yahoo 格式化。A 股路线继续在原有准入层保证 CNY、元值、单位与期间口径。 |
| Jev `TYPESAFE_BASE_URL`，`b838e25` / [#1416](https://github.com/TauricResearch/TradingAgents/pull/1416) | defer | 解决上游额外帖子筛选服务的 endpoint，不解决当前研究输出；此前暂缓的外部筛选方向没有被本轮重新批准。 |
| 加密资产 Reddit 社区，`c925f60` / [#1461](https://github.com/TauricResearch/TradingAgents/pull/1461) | defer | 当前主要 A 股，无直接收益。 |
| 欧元区 FRED 别名，`b3ca569` / [#1465](https://github.com/TauricResearch/TradingAgents/pull/1465) | defer | 只在具体研究假设确实受相关宏观因素影响时再补，不默认向每份 A 股报告加入宏观内容。 |
| 分析时并行结算所有历史交易决策，`f65fcab`、`5d8de36`、`11dab3b` | reject，执行功能 | 本地 legacy decision log 已只读。恢复该链路会新增行情和反思模型调用，以持有期收益解释研究质量；收益结果无法单独证明原假设成立。 |
| 整体合并图、交易路径、依赖与报告布局 | reject，整包升级 | 上游仍有 Trader、三角色风险讨论与组合决策报告；本地已退役这些执行节点。不能用上游整体结构替换本地已批准的研究流程。 |

发布版本号、logo、requirements 说明、HTML 依赖属于上述呈现或发布配套，
不构成单独的研究质量能力。引入 HTML 时再评估 `markdown-it-py` 依赖；不因上游发布
而整体提升 Python/pandas/LangChain 下限。

## 三项值得展开的借鉴

### 1. 日期错误必须可见，而非静默改变问题

本地 [as_of_window](../../../tradingagents/dataflows/date_window.py) 对无效起止日期
返回截点当天。离线函数对照复现：

| 请求 | 本地当前结果 | 上游 v0.6.0 |
| --- | --- | --- |
| start=`2026-09-26X`，end/cutoff=`2026-10-03` | `2026-10-03..2026-10-03` | 抛出起始日期错误，工具反馈格式要求，不请求数据源 |
| 合法历史窗口 | 原窗口 | 原窗口 |
| end 超过 cutoff | 截到 cutoff | 截到 cutoff |
| 整个窗口超过 cutoff | 保持跨度并平移到 cutoff | 相同 |

建议改造范围是经典工具的参数入口，不能把 native 的代码固定窗口改成自由模型窗口。
继承本地 `trade_date_from_state` 的严格状态校验与目标 ticker guard；无效输入不得发起
数据请求。工具反馈需可识别为参数错误，不能作为证据或正常数据。错误修复属于有界
预算内操作，不新增无上限纠错循环。

上游把错误作为工具返回文本是一个可用起点，移植时需核对本地 ToolNode、错误状态和
Evidence Steward 的消费者，不能只复制 `try/except`。关键验收是供应商零派发、窗口
没有被静默缩短、正常截点和身份约束保持有效。

### 2. 把离线报告做成研究简报

上游 [report_html.py](https://github.com/TauricResearch/TradingAgents/blob/v0.6.0/tradingagents/report_html.py)
禁用模型原始 HTML 和图片，以内联 CSS、自包含文件和 CSP 限制外部加载。值得借鉴。
但其 `render_report()` 遍历全部分组及 agent 全文，且沿用分析、研究、交易、风险、组合
五组报告，没有完成内容压缩或按决策重要性排序。

建议以本地 committed `research-record-v1` 为唯一输入：

- 主区：研究问题/截点、判断、最多三条关键依据、最大疑点、下一步验证。
- 可展开详情：保存的原文/页码/来源、事实与条件性推断、假设、挑战、已执行核查、量化输入。
- 重大风险、缺失及质量限制不能为了短而隐藏；工程状态与原始过程保持次级入口。
- HTML 与 Markdown/Reader 同源，导出不调用模型或供应商，也不改变已保存的历史记录。

此能力主要改善离线阅读与分享，不是提升分析质量的证明。工作台的 native Reader 已有
上述主区，先完成普通用户可选入口和阅读验收，再决定是否需要离线 HTML，能减少重复建设。

### 3. 同一模型按任务调整 effort

用户在评估后明确：没有资源使用多个模型，目前使用 DeepSeek V4.1 Flash，
并确认使用官方 API，希望通过调整 effort 分配推理资源。当前计划因此收窄为单模型策略，暂不实施上游
跨供应商/模型配置能力，也不安排大规模付费模型组合对照。

本次核实的 [DeepSeek 官方思考模式文档](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)
列出实际思考档位 `low / high / max`，默认 `high`；`medium` 和 `xhigh` 都映射到
`high`，不能视为额外档位。官方[更新日志](https://api-docs.deepseek.com/updates/)
与[模型说明](https://api-docs.deepseek.com/zh-cn/)确认 V4.1 Flash 使用模型 ID
`deepseek-flash`，旧的 `deepseek-v4-flash` 暂时由 V4.1 Flash 提供服务。
OpenAI 兼容接口的官方地址为 `https://api.deepseek.com`；Chat Completions 将
`reasoning_effort` 放在顶层，使用 OpenAI SDK 时将 `thinking` 放在 `extra_body`。

不同 effort 是同一模型的推理投入差异，仍共享模型知识和盲点；不能把它说成模型
多样性或统计独立验证。专项/挑战的上下文隔离和真实工具核查仍承担各自的职责。
也不能先验认定更高 effort 总会更准确或更低 effort 一定更省总成本；错误后的额外
修复、输出截断和运行时间都需要计算。

对当前方案重要的官方接口约束：

- [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 思考模式
  不支持 `tool_choice=required` 或指定具体工具，发送会返回 400；不能把 Responses API
  的工具选择能力当成当前 Chat Completions 的能力。
- [思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)携带 `tools` 时，后续请求
  必须完整回传已有 `reasoning_content`，包括此前没有调用工具的轮次。它服务于接口
  连续性，不是报告中事实正确的证据，也不应默认展示在研究简报中。
- [JSON Output](https://api-docs.deepseek.com/guides/json_mode/)提供 JSON 格式能力；
  提示中须要求 JSON，输出上限须合理，仍可能出现空内容或截断。
  工具 schema 的 [strict 模式](https://api-docs.deepseek.com/guides/tool_calls/)属于
  `/beta` 的独立能力，不等于普通接口支持 `response_format=json_schema`，也不保证主张真实。
- 未显式设置 `max_tokens` 时，思考模式默认 64K，`max` 为 128K；这是输出上限，
  不是每次必然消耗量。effort 策略必须与输出上限、剩余时间及实际 token 使用一起评估，
  不能用最终报告字数估计全部调用成本。

可供确认的分工原则（尚未实施或选定具体运行策略）：

| 工作 | 推理投入方向 |
| --- | --- |
| 数据校验、数值计算、已保存记录的排版 | 继续由代码完成，无新增模型调用 |
| 必须交给模型的简单提取/整理 | 可考虑 `low`，需要检查引用、遗漏及结构有效性 |
| 专项解释、提出可证伪假设 | 以 `high` 作为候选基线，根据任务复杂度再调整 |
| 反证与最终综合 | 保留充分投入，先考虑 `high`；复杂且确有需要时再评估 `max` |

本地 [provider_kwargs.py](../../../tradingagents/llm_clients/provider_kwargs.py) 已传递
全局 `deepseek_reasoning_effort`；仓库默认值为 `high`，不代表用户运行时一定没有覆盖。
[NativeModelCaller](../../../tradingagents/execution/native_model.py) 目前各阶段读取同一
配置，只有 synthesis 与其他阶段的模型选择有区别，尚无按角色设置 effort 的机制。
其提议通过 JSON 解析、schema 及引用校验，而非上述工具式结构化输出封装；不能把
工具参数兼容问题直接推定为 native 全流程失败。

本地另有一个应先处理的名称兼容缺口：
[capabilities.py](../../../tradingagents/llm_clients/capabilities.py) 登记了
`deepseek-v4-flash`，未登记 `deepseek-flash`；后者落入通用默认能力。
离线使用现有封装和已安装 SDK 构造绑定，确认旧名称省略 `tool_choice`，新名称
却生成强制指定函数的参数，与官方思考模式约束冲突。这个结论针对调用
`with_structured_output()` 的路径，未以真实请求复现 400；不能宣称整套运行都失败。
[model_catalog.py](../../../tradingagents/llm_clients/model_catalog.py) 也仍以旧名称展示 Flash。
切换模型 ID 前应同步能力登记与选择入口，并做参数构造核查，不能只改配置字符串。

实施分阶段策略需要显式配置/校验、按 stage 生成调用参数、保存策略与配置指纹，
使恢复采用原策略，并保留 `max_retries=0`、剩余时间、输出上限与 durable 额度。

官方平台与参数档位已确认；实际运行配置本轮未读取，也未更改模型 ID。未来如需验证，只在
已保存证据上做小范围、固定预算的 effort 对照，检查事实错误、关键风险遗漏、推断
越界、耗时与实际费用；没有付费试验授权时只做离线参数/恢复验证。
本轮仅更新评估方向与兼容核查记录，没有更改业务源码、运行参数或执行付费调用。

## 流程各环节的必要性

```mermaid
flowchart LR
    Q[明确研究问题和截点] --> E[代码准入并冻结证据]
    E --> H[按有证据的维度提出假设]
    H --> C[一次独立上下文挑战]
    C --> V[按关键条件做有界核查]
    V --> S[一次综合与代码校验]
    S --> R[简报和按需证据详情]
```

| 环节 | 为什么需要 | 何时应减少工作或降级 |
| --- | --- | --- |
| 问题/身份/截点 | 防止收集和分析与用户问题无关的内容 | 输入不明确或身份冲突时先确认，不猜测 |
| 证据准入/冻结 | 所有后续解释共享可追溯输入；防止时间、单位、覆盖错误 | 数据失败返回 unavailable/partial，不能产生无事件结论 |
| 经营、事件、市场专项 | 解释不同机制：经营是否支持、事件是否兑现、价格/量化背景如何 | 无合格专项事实时跳过；某项是否提高质量仍需消融对照，不默认证明三项永远必要 |
| 一次挑战 | 提出替代解释、遗漏与失效条件 | 允许零个挑战；不强制生成多空立场，不做重复轮流辩论 |
| 有界工具核查 | 检验可执行条件，给出确定性结果与输入版本 | 仅核查能改变判断的条件；缺正文/工具失败/超预算仍未解决 |
| 一次综合及代码校验 | 把支持、反证、限制整理为判断，检查引用与维度资格 | 不调用第二个摘要模型；数值条件通过不代表经济假设整体成立 |
| Reader/导出 | 让用户直接读结论并核查原文 | 读取不能刷新证据、触发模型、重写历史结果 |

上游 v0.5.2 已新增分析师并行、工具额度用尽后的收尾和原子缓存写入。这些属于上一版，
不是 v0.6.0 新的推理能力。本地 native 已有隔离专项、固定汇合、跳过无事实角色及有界
阶段；不能直接将上游并行图接入仍共享 messages 的 classic。上游内存结算的“一次性
结算、逐条保留已完成结果”可作为通用恢复设计参考，本地已有 durable dispatch/cached
result，仍需以相关恢复回归证明等价，不能恢复已退役交易写入端。

## 当前最值得先做的工作与待决边界

建议顺序：

1. **明确入口和做质量对照**：使已存在的 evidence_v1 能以可选方式进入工作台；
   默认是否迁移留到对照与真人阅读验收之后。该入口属于本地产品完善，不是上游已有功能。
2. **修正通用日期纠错**：只处理当前仍有相关经典工具入口的路径，不改 A 股供应商路线。
3. **按需增加同源 HTML 导出**：若用户需要离线/打印/分享，再基于统一记录适配。
4. **最后评估同一模型的 effort 分工**：使用官方单一 DeepSeek V4.1 Flash；先补齐当前
   模型名称的兼容适配，再在既有预算内考虑按任务分配推理投入。多模型/多供应商不在当前计划内。

建议质量对照使用已规划案例类别，覆盖财务或价格缺失、公告标题与正文不一致、
披露晚于截点、公司身份冲突、重大风险拥挤、工具失败、预算耗尽和已保存运行恢复等。
需要同时评价“遗漏风险”和“错误自信”，不能仅比较报告更短、运行成功或收益涨跌。

尚需用户作实施决定的事项：可选工作台入口/默认迁移范围、离线导出是否必要、
各阶段 effort 与验证预算。这些不阻碍本轮文档调整；官方接入已确认，
具体运行策略和兼容修复尚未实施。

## 验证范围与复核路径

- 已阅读发布说明、25 个新增提交主题、v0.6.0 核心实现和相关上游回归用例；
  补读 v0.5.2 差异，并逐项对照本地当前架构、代码与操作文档。
- 在临时目录运行 4 个日期函数对照场景，3 个正常/越界控制场景一致，无效起始日期行为不同。
- 用注入的客户端与参数构造器验证上游 provider/endpoint 分离；未调用真实 SDK。
- HTML 的禁 raw HTML、禁图片、CSP、全章节遍历为源码检查，未进行浏览器/手机/打印验收。
- 已阅读 DeepSeek 官方首页、更新日志、模型说明、思考模式、Chat Completions、
  JSON Output 与工具调用文档；离线能力查找和 SDK 绑定构造确认新旧 Flash 名称的
  `tool_choice` 差异。绑定核查没有执行 `invoke` 或 HTTP 请求。
- 临时复核脚本：`/private/tmp/tradingagents-v060-review-probes.py`。
  它抽取原始函数 AST，注入依赖，不导入整个业务运行器，不访问凭据、供应商或用户数据目录。
- 未执行付费模型调用、投资准确率评估、完整 pytest 或上线操作。
- 文档检查与 diff 检查结果在本轮交付消息中报告；没有修改业务源码、测试、静态前端或依赖。

本轮不承诺零错误或收益改进。明确已观察行为、推断收益和未验收内容，
正是这次选择性借鉴应保留的核心约束。
