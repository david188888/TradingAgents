# 统一公司投资吸引力研究与一轮证据质询

- Status: Frozen Design
- 日期：2026-10-11
- Do not use this document as evidence of current implementation behavior.
- 当前行为入口：[文档索引](../../README.md)、[研究操作说明](../../operations/evidence-research.md)、[研究记录契约](../../contracts/research-record.md)。
- 用户已确认：只有一个研究模式；核心回答投资吸引力；采用一轮定向质询；参考上游默认一轮，但保留本项目的证据约束。
- 本文记录已批准并完成本地实施的设计决策；当前行为以统一公司研究契约和代码为准。

## 1. 目标与第一性原理

用户输入公司和分析日期，系统回答：**截至分析时点，结合经营、当前估值、事件与市场风险，这家公司是否具有投资吸引力，为什么，什么证据会改变判断？**

研究模式是系统的组织方式，不是用户的业务目标。经营、估值、事件与市场风险必须作为同一次研究的维度，而不是要求用户先在公司、催化、持仓三种模式之间选择。判断来自合格事实、明确推理和对反证的处理，不能来自投票、固定看多/看空角色或重复争论。

成功标准：

1. 单个和批量公司研究都只有一个新建入口，没有研究模式、辩论轮数或持仓输入选择。
2. 正文首先呈现投资吸引力倾向及理由，随后可追溯至证据、质疑、回应与综合裁决。
3. 有挑战时，相关专项最多回应一次；没有挑战时合法跳过，不制造分歧。
4. 缺资料、回复失败、反证未解决都会影响结论的范围或可信度，不被成功状态掩盖。
5. 历史研究的模式、维度、预算、哈希、恢复行为与已发布字节保持原义。

## 2. 已考虑的方案

| 方案 | 结果 | 决定 |
| --- | --- | --- |
| 仅隐藏模式选择 | 仍沿用原公司研究目标和三个评价维度，事件难以进入完整结论，也没有质询回应 | 不采用 |
| 自动在旧三种模式之间选择 | 系统仍分裂研究范围，自动判断持仓需要未提供的账户事实 | 不采用 |
| 统一公司目标、四个评价维度、一次质询回应 | 完整回答用户问题，保留可追溯证据和明确资源边界 | 采用 |

本设计不增加多轮辩论、账户管理、自动交易、目标仓位、收益承诺、新数据供应商或无界取数。LLM Provider 和具体模型的配置沿用现有能力；截图中的三个选项属于研究模式，不是三个模型。

## 3. 用户入口与时间范围

新建研究保留股票代码、分析日期、模型配置和可选补充关注点。分析日期默认今天。单个与批量研究使用同一目标、同一版本、同一流程。模式下拉框及持仓事实表单移除。

统一研究评估分析日期可用的事实及该日期对应的价格/估值。旧催化模式的固定未来 84 天不成为新研究默认期限；事件分别说明已发生、已公布但尚未兑现、或待验证，引用证据中实际存在的日期。经营推理声明相应报告期或兑现条件，不自动给出某个持有期内的涨跌预测。没有明确兑现日期时说明时间不确定，不编造期限。

补充关注点沿用后置语义：在完整独立研究保存后，依据保存证据补充回答。它不参与资料选择、专项、挑战、回应或综合，不改写主结论。没有补充关注点时不产生额外模型调用。

新建请求在 Web 边界统一为 `research_profile=evidence_v1`、`mode=company_research`、无 holding/portfolio。兼容保留旧 mode 枚举供读取和恢复使用，不把它当作新建选项：

- mode 缺省或显式 company 都接受；不根据持仓输入自动切到 holding。
- 显式 catalyst/holding 新建请求返回 HTTP 422、稳定代码 `unified_research_mode_required`，定位 `mode`。
- company/缺省 mode 带 holding 或 portfolio，继续采用现有 `holding_not_allowed` / `legacy_portfolio_not_allowed` 错误。
- 新建不支持的 profile 继续 HTTP 410，不借单模式修改这条边界。
- 错误优先级固定：可解析请求先检查 profile 的 410，再检查非法新建 mode，最后按现有次序检查 holding/portfolio（两者同时存在返回 `holding_legacy_conflict`）。Pydantic 无法解析字段时仍由现有 schema validation 返回 422，不承诺覆盖这种更早的错误。
- 单个、批量、历史“重新研究”都经过相同的新建校验；旧记录可以读和恢复，旧非公司模式“重新研究”不能静默转义。UI 提供明确的“新建公司研究”动作，重新输入/确认公司和日期，不复制旧持仓内容。

## 4. 流程与角色职责

```text
合格来源收集与证据冻结
  → 经营 / 事件 / 市场专项独立提出假设
  → 独立挑战（最多三个现有挑战）
  → 现有代码条件核查（沿用有界验证）
  → 被质疑专项各回应一次（零至三次调用）
  → 综合投资吸引力、四维判断和逐项分歧裁决
  → 校验并保存完整主记录
  → 可选后置关注点回应
  → Reader / Markdown 只读展示
```

| 单元 | 输入与职责 | 输出及边界 |
| --- | --- | --- |
| 来源和代码宿主 | 沿用最小充分证据取数、截止时点、确定性计算与来源资格 | 冻结事实、估值输入、局部核查；模型不能新增事实 |
| 经营专项 | 财务、经营明细及合格估值证据 | 经营与估值假设、必要/失效条件、替代解释；估值仍属于此专项，避免新增第四个初始模型调用 |
| 事件专项 | 合格公告与正文 | 已发生变化、未来事件及其兑现条件；标题不证明事件兑现 |
| 市场专项 | 合格历史行情和量化结果 | 历史市场背景与风险；价格统计不证明内在价值 |
| 独立挑战 | 三专项合并假设与冻结条件，隐藏作者元数据 | 零至三个针对现有假设的挑战，不强制看多或看空 |
| 专项回应 | 本专项原输入、自己的假设、定向挑战及绑定的已保存核查结果 | 每个挑战一条回应；最多一次逻辑调用/专项，不获取新资料或读取其他专项草稿 |
| 综合 | 四维可引用依据、全部挑战、核查、有效回应、失败与覆盖信息 | 投资吸引力、理由、主要反证、条件和逐项裁决；不按角色票数判定 |

初始专项隔离保持不变。新增回应阶段位于挑战和条件核查之后，原假设不被覆盖。宿主在生成假设时保存 `hypothesis_id → role` 的绑定；挑战仍用不带作者信息的假设 ID，定向回应时由宿主解析归属，模型不能选择或冒充作者。

一个角色收到多个挑战时，一次调用返回该角色所有挑战的回应。固定角色顺序先预留预算，最多两个专项回应并发，按固定顺序合并。无挑战或未产生假设的角色不调用。回应阶段不再生成第二轮挑战，不触发第二轮验证或取数。

## 5. 契约与版本边界

新流程使用 `evidence-production-v7` / `native-research-kernel-v6`，在运行 identity 中冻结单模式目标、预算、质询策略和重试策略。V1–V6 的分支与 Reader 资格策略保持冻结。

新增 `UNIFIED_*` 版本/目标/预算常量，不重定义现有 `FOCUS_*` 的 V6 取值，不全局替换旧 `BASE_QUESTIONS`，避免历史恢复使用新的目标或预算。

`ResearchRecordV1` 保留现有外层 contract，新增可选、显式版本化的 `dialogue` 包；缺省时序列化完全省略，避免改变旧记录/种子哈希。新增 `ResearchAssessmentV3`，通过现有 schema discriminator 区分。新建 V7 的最终记录必须包含 V3 assessment 和 dialogue；旧版本不得接受这两个新产物作为自身输出。

以下是契约职责，详细类型只在 canonical Python schemas 定义，不另在文档复制大段 schema：

- **回应提议**：指向分配给本专项的 challenge/hypothesis；声明维持、修正、撤回或无法回答；提供理由、引用和剩余未知项。每条挑战必须恰好回应一次。引用允许本专项原合格事实及与该挑战绑定的已保存验证事实/核查 ID，禁止其他专项的新事实、推断充当事实或未保存 ID。
- **dialogue-v1 包**：最终证据 snapshot、原假设作者绑定、各角色的回应结果和状态。完整保留原假设；修正是另存的推断性回应，不变成新的事实、可执行条件或新验证任务。
- **缺席回应**：宿主生成 typed unavailable，记录对应角色/挑战与稳定原因；不让模型代写该专项观点。无挑战记为 not_applicable，与调用失败区分。
- **分歧裁决**：V3 assessment 新增独立 typed `adjudications`，综合对每个挑战恰好给出一项处理，引用相应有效回应或缺席状态，并解释该争议如何保留、削弱或撤回原假设、影响整体结论。现有 `challenge_assessments` 继续保留代码生成的 V2 局部检查 outcome，不能用模型裁决覆盖或合并这两种结果。不得把模型的“维持观点”改成已验证。
- **投资吸引力**：V3 assessment 增加四态倾向 `favorable / neutral / unfavorable / insufficient_evidence`，对应有条件看好 / 暂无明显吸引力 / 偏谨慎 / 证据不足。整体 judgement、依据和反证引用保存的 claims/challenges；V3 新增 bounded 支持/反对理由，每项包含理由文字、合格 claim/fact ID 和可选 response ID，支持与反对分别最多三条。neutral 表示已有依据但暂无明显吸引力，不能代替资料不足。
- **改变判断的条件**：V3 保存一至三条条件，每条绑定公开记录中的 `hypothesis_id` 与其保存的 `invalidation_conditions` 文本和索引，校验文本精确一致；缺假设的宿主不足 fallback 保存空条件并解释缺口。不得只引用 journal 中的 `condition.*` ID。Reader、Markdown 和外部消费者仅用最终记录即可解析条件。

原有 `DIMENSIONS_BY_MODE` 不全局修改。通过 assessment/workflow 版本明确选择维度，所有 producer、schema validator、publication gate、saved Reader gate、Markdown renderer 同步使用该版本：

- V1/V2 assessment 沿用旧模式维度和顺序。
- V3/company 固定四维：`operating_quality`、`valuation`、`catalyst_delivery`、`market_context`。新 Reader 将其中 catalyst_delivery 显示为“事件影响与兑现”，没有固定 84 天；旧催化研究保持原来的“催化兑现”和 84 天语义。
- V3 不允许 holding/catalyst mode，也不允许 `forward_window_calendar_days=84`。

原假设 ID、原条件、证据内容与核查语义不因回应改变。V3 局部核查仍沿用代码生成的 V2 outcome；对经济母问题的裁决是推理评价，与工具核查 outcome 分开。

宿主按有效回应生成 **effective support** 集合用于 V7 的综合和最终发布，而不是只在提示词中提醒：

- withdrawn 或 revised 的原 inference claim 保留用于追溯和反证，但从各维度的肯定性 claim pool、key_claim_ids 与支持理由集合中移除，不能把原断言继续当作支持。
- revised 回应不生成新事实/假设；其修正文字仅能通过 V3 理由引用有效 response ID 及该回应允许的合格事实依赖进入综合。对应维度使用这些合格事实 ID，并展示修正后的判断，不能只引用原 assertion。挑战和原假设绑定依然保留。
- maintained 回应仍受原依赖与挑战资格上限约束；unanswerable/unavailable 不构成支持证据。综合可以引用任何仍合格的原事实来提出受限判断，但不能据此冒充失败专项的回应。
- 同一原假设涉及多个挑战时，只要任一有效回应撤回或修正，即禁止将原 inference 当作肯定性依据；存在多种修正时全部保留，综合说明差异，不能自行合并成更强的事实。
- 发布 gate 重新计算上述集合，拒绝综合将撤回/修正的原断言作为肯定性支撑、把无效/缺席回应作为支持、或把回应引用扩张到其他资料。追溯与反证中的原 claim 引用可以保留，但不能提升倾向或维度资格。

## 6. 结论资格与缺资料处理

整体倾向是有条件的研究判断，不是研究成功标记。代码控制发布资格，模型提供受证据约束的解释。

1. 合格经营依据或分析时点的价格/估值依据缺失，整体必须为 insufficient_evidence，仍展示已取得的局部分析。历史涨跌、低 PE 或同行倍数不能代替缺失的估值依据。
   经营最低资格包括至少一条具公司身份、报告期/单位绑定的合格财务事实，以及经营维度实际引用的证据；估值最低资格包括对应分析时点的合格价格/估值字段和实际引用。只有 `record.valuation` 对象而无合格字段/引用不算满足资格。只有现价和 PE、没有可用代码估值锚点时，可以说明价格定位，但禁止 favorable；不足以形成其他有依据倾向时使用 insufficient_evidence，不能由低 PE 自动判断便宜。favorable 另须引用现有可用代码估值锚点与其假设，并说明关键经营依据；不新增估值算法或要求模型创造合理价格。
2. 四维均保留，各维度沿用来源分区和资格上限。事件/市场输入不足时相应维度 unresolved，整体说明缺口；不能写成没有事件或没有市场风险。
3. 已有 critical 经济挑战尚未获得足以消除它的事实时，不允许发布 favorable。继续沿用经济挑战 unresolved 的边界；回应的措辞、各角色同意或谓词检查成功均不能解除这一约束。资料充分时仍可作有依据的 unfavorable 判断。
4. material/minor 分歧必须出现在逐项裁决中；favorable 仍须说明相关条件与反证，不能只列支持理由。
5. 任何需要的专项回应 unavailable，使研究 completeness=partial、quality=LOW_CONFIDENCE。综合可以在明确说明缺席的情况下形成受限判断，不能宣称完整辩论结束。
6. 只有合格、属于当前记录的非 unknown claims 可作支撑。维持/修正的回应须有合格引用；撤回/无法回答可以没有支撑事实，但必须说明原因，且不能被综合作为支持性证据。
7. 综合或发布校验失败时，沿用诚实失败/部分产物语义，保留已保存阶段。不得为了填充四态字段编造结论。宿主的资料不足 fallback 与模型结论明确区分。

不增加未经校准的置信度百分比、综合评分或收益预测。现有 PASS/LOW_CONFIDENCE 表示发布/证据边界，不宣称投资结论已被现实验证。

## 7. 调用预算、重试、恢复与失败

正常逻辑调用由原来的三专项 + 挑战 + 综合，增加零至三个专项回应：**主流程最多 8 次，补充关注点最多 1 次**。保留整轮实际模型尝试上限 12；因此全角色回应加 focus 正常最多 9 次，剩余尝试额度由现有失败修复/有限重试共享，不保证每个角色都能用满重试次数。

V7 identity 单独冻结 `{main_analysis: 8, focus_response: 1, model_attempts: 12}` 与现有分项修复/网络重试上限。V6 的 5/1/12 保持不变；不得全局提高 default budget 以影响旧运行。数据调用上限、最大三条有界验证与用户当前 active timeout 保持现有配置，未使用的回应额度不自动转为取数或额外辩论。

回复使用现有模型传输和有限瞬时重试，重试相同冻结上下文，不算第二轮辩论。额度/权限/能力/协议/不完整流的永久失败边界和 focus 一次尝试边界保持。任何预算耗尽或 active deadline 达到都应停止，不能增加轮数、偷偷换模型或绕过取消。

回应 stage 固定为 `response_operating_quality`、`response_event_context`、`response_market_context`，logical IDs 固定为 `native.<stage>`。角色原假设绑定、挑战分配与完整回应上下文的 digest 在派发前保存；恢复时验证 workflow、目标、snapshot、配置、预算和上下文完全一致。

- 已保存有效回应从缓存恢复，不重复调用。
- 未派发的预留沿用 ledger 规则；已经派发但结果未知不自动重放，也不退还已耗费的额度，保存 typed unavailable。
- 一个回应失败不会丢弃其他专项结果；与挑战绑定的缺席明确进入综合。
- checkpoint/persistence 身份冲突、引用跨角色/悬空和取消沿用控制错误，不能降格为普通供应商缺资料；无效回应不能进入公开 dialogue。
- optional focus 失败不会丢弃已保存主研究。publication lifecycle、取消仲裁和候选哈希保持现有边界。

## 8. Reader、Markdown 与可观测性

Reader 继续以保存记录作为唯一主研究源，信息顺序为：

1. 投资吸引力倾向、综合理由、分析日期和结论限制。
2. 主要支持依据、主要反证与改变判断的条件；均能定位保存来源。
3. 经营、估值、事件、市场四项判断。
4. Agent 分歧：原假设 → 挑战 → 代码核查 → 专项回应 → 综合处理；展示实际缺席和跳过。
5. 完整来源、局部检查、技术诊断及可选补充关注点。

现有页面布局及证据侧栏复用，不另造可视化应用。新回应阶段接入 Python/TypeScript 的版本化角色注册表、SSE 状态 reducer、任务 effort mapping、SDK 观察/诊断、Reader process/agent projection 和预算统计。只有 V7 展示新阶段；旧运行不凭空出现回应角色。经营/事件/市场回应沿用对应专项任务的模型层级与 effort，不能因新增 stage 意外回退到未配置策略。

正文先校验公开记录；未发布的提议可以沿用受保护的“已保存，待发布”阶段状态，但不能被作为最终研究证据呈现。公开 agent endpoint 仅返回封闭提议/记录字段，不泄露 raw prompts、响应、凭据或 checkpoint。

Markdown 和 native 对外消费都来自同一个最终记录，携带 V3 结论与 dialogue 的资格信息；公开摘要不能遗漏未回应挑战。native 外部消费继续使用 `/reader/record`，没有配对 `research-package-v1`；不新增 native package。保留 classic 的 research-package 契约与读取语义，文档明确旧包与 native record 的消费路径。

移动端长理由与来源 ID 可换行、无横向溢出。点击阶段查看详情后滚动并转移焦点；收起后焦点回到触发按钮。键盘和重复点击维持现有交互语义。

## 9. 代码所有权与实施顺序

| 层 | 主要 canonical 文件/模块 | 负责内容 |
| --- | --- | --- |
| 提议与记录 | `tradingagents/agents/schemas/_native_stage.py`、`_research_assessment.py`、`_research_record.py`、新增小型 dialogue schema | 封闭回应、V3 assessment、引用/唯一性/版本验证、旧字节兼容 |
| 策略与图 | `tradingagents/research/native_versions.py`、`native_policy.py`、`tradingagents/graph/native_research.py` | 新版本、四维资格、作者绑定、挑战分发、一次回应、综合 |
| 执行和持久化 | `tradingagents/execution/native_runner.py`、`native_model.py`、`native_publication.py`、`tradingagents/runtime/catalyst_checkpoint.py` | stage schema、预算、恢复、取消、发布 |
| 创建边界 | `tradingagents/web/schemas.py`、`api.py`、`manager.py`、batch 路径 | 新建单模式，旧请求读取/恢复，新建错误 |
| 阅读与审计 | `tradingagents/web/native_reader_versions.py`、record/process/agent/audit projections、`tradingagents/runtime/reports.py` | 按保存版本资格判断及完整追溯，保留 classic package 路径 |
| 前端 | `frontend/src/api/contracts.ts`、`hooks/useConfig.ts`、controls、state/model、readerExplanation、NativeReader/ReaderAgentOutput/NativeResearchPage | 移除模式/持仓表单，回应阶段，结论与分歧 |
| 当前文档 | 中英文 README、ARCHITECTURE、docs/context、索引、research-record/evidence-research/package/observability 文档 | 单模式目标、质询、预算、历史兼容及限制 |

顺序为 schema/资格 → 内核/持久化 → Web/公开投影 → 前端/生成资产 → 文档/验收。新增文件各自承担单一职责，不把全部新逻辑继续堆进已有大文件；不顺带重构无关 classic/catalyst 兼容代码。

## 10. 验收

在实现前对照知识库和 canonical contract 确认测试约定。测试验证真实约束，不只镜像实现：

- 新建单个/批量仅支持公司；旧非公司新建报稳定 422；默认 profile 及旧 410 边界不漂移；历史恢复不经过新建限制。
- 无挑战零回应，有挑战只路由作者；同角色多挑战只调用一次；三角色回应不超三次；固定顺序不受并发完成时间影响。
- 跨角色/未保存/重复/遗漏引用拒绝；原假设和冻结条件在维持/修正/撤回后不变；回应不能创造事实或验证成功。
- 综合独立 adjudications 覆盖所有挑战并引用真实回应/缺席，V2 局部 outcome 保持代码生成；经营/估值不足强制 insufficient_evidence；仅对象存在/仅价格 PE 无锚点禁止 favorable；critical 未解决禁止 favorable；事件缺口不得写成没有事件。
- 原假设被撤回/修正后仍作为 key claim、肯定性维度/理由支持时拒绝；有效修正只从 response 与允许事实进入判断。改变判断条件无法由最终记录独立解析、或文本/索引错配时拒绝。
- 已保存回应恢复不再调用；未知派发不重放；失败、超时、取消、预算耗尽、发布冲突不导致追加取数或重新辩论。
- 全流程预算 8 + optional 1、attempts≤12；V6 5/1/12 与旧 SDK 统计保持；focus 隔离、一次调用、失败不丢主记录。
- V1–V6 fixture 字节/哈希与旧三模式维度照旧；V7 字段缺失/冒充旧版本无法公开；Reader、Markdown、native 外部消费使用同一保存数据，classic package 路径不扩张。
- Vitest/Playwright 覆盖单入口、四维、分歧与缺席展示、阶段状态、键盘/焦点/重复点击、390px 无横向滚动；浏览器不能用本地编造内容代替后端产物。
- 运行 contributor 必需 docs/Ruff/frontend ci/typecheck/build、受影响 pytest/Vitest/Playwright；生成 `tradingagents/web/static/` 并 `git diff --check`，保留无关未提交文件和用户数据。

离线与浏览器验收不证明研究准确性。需要真实模型验证时先用一家公司检查完整推理与证据追溯，记录实际来源缺口、调用数和判断限制；这一设计不自动授权付费调用或自动重放历史运行。

## 11. 上游参考与设计状态

核查日期 2026-10-11，上游 main tree commit `1394a3f72aa4393e1a98f51b382434c4b4c2d972`：

- [默认配置](https://github.com/TauricResearch/TradingAgents/blob/1394a3f72aa4393e1a98f51b382434c4b4c2d972/tradingagents/default_config.py)：投资辩论 1，风险讨论 1。
- [终止逻辑](https://github.com/TauricResearch/TradingAgents/blob/1394a3f72aa4393e1a98f51b382434c4b4c2d972/tradingagents/graph/conditional_logic.py)：投资一轮是看多/看空各一次，风险一轮是三个角色各一次，随后交给经理综合。
- [CLI 深度](https://github.com/TauricResearch/TradingAgents/blob/1394a3f72aa4393e1a98f51b382434c4b4c2d972/cli/prompts.py)：提供 1/3/5；README 的 2 是调整示例，不能推导为质量最优轮数。

这些事实支持有限轮数作为资源边界，不证明本项目的一轮质询或上游辩论的投资研究质量。采用定向证据质询是用户已确认的本项目设计。

> 🧠 **From Hindsight memory (独立基础研究与后置关注点回应)** — 既有独立主研究先保存，补充关注点只读取冻结证据，不能改写主结论；本设计已对照当前代码确认并保留这一边界。

设计流程记录：上下文与方案比较已完成；目标与一轮质询已获用户确认；独立规格审查完成两轮，四项阻塞修订后通过；用户书面审阅是下一步。未修改运行代码、未启动新研究、未改变本地服务。
