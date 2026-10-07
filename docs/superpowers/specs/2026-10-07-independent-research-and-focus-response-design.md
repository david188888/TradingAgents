# 独立基础研究与后置关注点回应

Status: Proposed

Do not use this document as evidence of current implementation behavior.

2026-10-07 用户确认方案 A：先完成并保存独立分析、挑战与综合，再单独回应用户关注点。本规格细化这一已确认方向；规格审查与用户书面规格确认完成后进入实施计划。当前行为以 [文档索引](../../README.md)、[Web 研究操作](../../operations/evidence-research.md)和[研究记录契约](../../contracts/research-record.md)为准。

## 1. 问题、目标与范围

当前 `graph/native_research.py` 以用户 `research_question` 替换模式默认问题，并传入三个专项、挑战和综合。最新保存样本 `run_20261006T080541489282Z_c275dbb3`（002130.SZ，2026-10-06，V5）中，9 条专项推断和经营、估值、市场三个维度均围绕“核心业务与 AI 上下游供应链是否强关联”；当前 Reader 又以该问题与回答开篇。问题已经影响内容生成，改界面标签不能修复它。

目标是让研究模式决定基础任务，让已保存证据决定重要性，让用户关注点成为附加的解释维度。填写关注点后，基础研究仍应发现其范围内的重要经营事实、估值限制、事件和风险；关注点不能挤占分析或挑战名额。独立性通过信息流隔离保证，不能只依赖“请保持客观”的提示词。

本次覆盖新建 Web 单项、批量的 `evidence_v1` 三模式、运行恢复、Reader、Agent 产物、审计计数和 Markdown。保留请求字段 `research_question` 及其现有 trim / 400 Unicode 字符校验，界面名称改为“补充关注点（可选）”。本次不改变数据源准入、研究维度集合、已有核查能力或旧流程拓扑；不补取 002130 的历史证据，不改写保存报告，不自动发起付费验收。

## 2. 第一性原理与可执行不变量

1. **基础任务独立**：模式与合格证据决定基础任务。用户关注点不得进入取数请求、冻结证据、专项、挑战、验证任务选择或基础综合的模型上下文；不得作为事实加入来源或 claims。
2. **重要性独立**：基础综合依据全部模式维度与证据影响程度选择关键依据、主要挑战、下一步。重大反证不得因与关注点无关而排除；缺资料是相应维度的边界，不是公司整体被否定的理由。
3. **先冻结再回应**：关注点模型调用前，完整基础记录必须已经持久化并验证摘要。它包括 assessment、维度、关键依据、挑战、核查、下一步和质量标记。关注点模块不能调用基础记录的写入接口。
4. **回应单向消费**：后置模块只能消费已冻结基础记录与原始关注点，产出独立附加物；不得增删基础事实、假设、挑战、已执行核查或修改 PASS / LOW_CONFIDENCE。
5. **失败隔离**：补充模型失败、格式错误、证据不足、额度耗尽或超时只影响补充回应。显式取消、全局存储损坏和基础发布失败继续遵循现有失败/取消规则，不能伪装成成功。
6. **历史语义固定**：旧 V1–V5 记录、提示词摘要、身份、已用预算、读资格和恢复保持原语义。新行为通过版本选择，不以新解释覆盖旧 `research_question`。

“全面”只指覆盖当前模式范围，不要求每个维度都有肯定结论。固定上下文相同能排除关注点输入造成的锚定，并不保证随机模型在两次真实调用中输出相同，也不能证明研究已无偏差。

## 3. 模块与数据流

新增生产版本 `evidence-production-v6`，基础内核版本 `native-research-kernel-v5`。V6 使用 V5 的数据能力和准入规则，但移除关注点输入；旧版本走原分支。

```text
模式 + 合格来源 + 合法持仓原假设
    → 冻结证据 V0 → 三个隔离专项 → 独立挑战 → 现有有界核查
    → 基础综合 → 持久化不可变基础记录及摘要
    → [有关注点且允许调用] 单次关注点回应 → 独立附加物
    → 原取消/发布仲裁 → 必需基础记录发布 → 可选附加物发布
    → Reader / Markdown / Agent 产物 / Audit
```

基础记录先持久化到 durable frontier，不提前将 run 标记 completed。现有 lifecycle authorizer 会进入 terminalizing，因此不得在关注点调用前提前执行它。最终仍只有一次 lifecycle 发布仲裁，用户在补充阶段请求取消时，按现有规则取消整次运行。取消仍是终态，不新增取消后 resume；保存的基础 frontier 保留供审计，只有既有 interrupted 状态可按原恢复入口继续。

### 3.1 模式拥有基础任务

为 V6 单独定义模式目标，旧 `QUESTIONS` 的恢复语义不变：

| 模式 | V6 基础目标与必查范围 |
| --- | --- |
| 公司研究 | 公司经营质量、估值定位与市场风险如何，哪些重要事件和证据可能改变判断，哪些关键问题尚未确定？覆盖现有经营、估值、市场维度，事件专项提供重要事件与风险。 |
| 催化研究 | 未来 84 天哪些催化可能改变判断，经营基础、兑现与失效条件、市场背景和关键缺口是什么？保留既有 84 日展望与维度。 |
| 持仓复盘 | 原持仓假设受到哪些新证据支持或挑战，经营、估值与市场风险如何，哪些条件需要重新核查？原持仓假设仍是此模式的合法基础输入。 |

模式目标传给核心模型，附带角色任务和现有维度规则。专项仍使用原合格分区与最多三条假设；挑战按证据质量、替代解释与重要风险选择，不强制多空、也不要求必须返回三条。用户关注点不能消耗这些槽位。

V6 collector 接收不含 `research_question` 的专用输入，避免当前 `vars(request)` 转发整份请求的隐式泄漏。关注点不参与基础 kernel identity、条件/假设/挑战 ID 推导、模型 context 或 prompt digest。完整 run identity 仍保存原字段用于恢复校验；基础身份和完整请求身份是不同职责。源文本自然出现相同主题是合法证据，不按“AI”等关键词删资料。

### 3.2 冻结基础记录

继续以 `ResearchRecordV1` / `research-record-v1` 表示基础研究，不向它追加关注点字段。V6 的 `assessment.research_question` 保存模式拥有的基础目标，而非原始用户输入。基础 judgement、dimensions、key_claim_ids、primary_challenge_id、next_check、quality 和 completeness 只能由基础综合及现有代码门槛生成。

在 `native.output` durable result 保存后，以 `canonical_sha256(record)` 冻结摘要，关注点执行器只拿经校验、不可变的记录。核心输出的持久化必须完成后才能 reserve 补充调用。回应后再次验证基础摘要；不一致为完整性错误，禁止发布被改写内容。

没有实际综合提议、仅生成 `native_synthesis_unavailable` 降级基础记录时，跳过关注点模型并记录 `base_synthesis_unavailable`。实际综合完成而部分维度 unresolved 的记录允许补充回应，并完整传递其限制。

### 3.3 后置关注点回应

新增独立 `execution/native_focus.py`，输入仅为基础记录、其摘要、原始关注点、现有 ledger、模型 adapter 与取消/截止回调。模块不能取得 collector 或基础 kernel 的调用入口；不联网补数、不开工具、不追加挑战或验证任务。

模型任务为 `native.focus_response`，使用 quick 模型，继承全局 effort；允许现有按任务配置增加此键。其提示词明确区分用户提问与来源事实，要求复用保存证据、呈现支持/不支持/未知与替代解释。它回答补充视角，不替代独立反证审查，不将基础推断升级为事实。用户文本作为不可信输入，不能覆盖角色或出版约束。

回应模型只产出闭合 proposal：answer（最多 1200 字符）、answerability（`answered` / `partial` / `unresolved`）、claim_ids / evidence_ids（分别最多 8 个、唯一且指向基础记录中的合格已保存资料）、limitations（最多 6 条，每条最多 300 字符）、suggested_next_check（可空、最多 300 字符）。`answered` / `partial` 必须包含支撑引用；`unresolved` 可无引用，但必须明确缺口。它们表示可回答程度，不表示验证成功。模型不得提供新的 source、claim、hypothesis、challenge、verification 或基础 assessment 字段。

在引用校验时拒绝 unknown claims、unavailable / unverified 来源、无保存内容、无 usable_as_of 或越过截点的来源。推断引用保留其基础事实绑定及假设身份。基础记录的所有维度限制、未解决挑战和质量标记同时在补充阅读中可达，引用不能关闭原挑战。

新 canonical schema 放在 `agents/schemas/_research_focus.py`：`ResearchFocusResponseV1`，公开契约 `research-focus-response-v1`。主机写入身份（run_id、ticker、mode、analysis_date）、input_snapshot_id、base_record_sha256、focus 和 status；input_snapshot_id 必须等于 frozen baseline 的 assessment.input_snapshot_id（包含已经完成的验证版本），不能仅绑定最初 V0。模型不拥有身份字段。status 为 `available` 或 `unavailable`；available 包含已验证 proposal，unavailable 不包含模型回答且有稳定 reason_code。未填写关注点不写附加物，不调用模型。

## 4. 预算、截止时间与恢复

基础 MAIN_ANALYSIS 仍最多 5 次，总 MODEL_ATTEMPTS 仍最多 12 次，其余现有额度不变。新 bucket `FOCUS_RESPONSE` 计入总模型尝试：V6 最多 1，旧 workflow 与其它 profile 为 0。默认 bucket 为 0，由 V6 显式启用并在其 checkpoint 中冻结预算政策；恢复从版本与保存政策校验，不放宽旧 ledger。补充阶段没有结构修复、网络重试或第二次摘要，最多发出 1 次 SDK 请求。

填写关注点意味着可能增加 1 次主 SDK 请求；它在所有基础工作之后 reserve，既不提前占基础总额度，也不挪用第五个主分析槽位。基础阶段用完总模型额度时，回应记为 `budget_exhausted`，保留基础结果。

延续当前整次模型/取数工作的绝对截止时间。补充启动时若已无剩余时间，保存 `deadline_exceeded`；有时间则使用剩余时间作为 SDK timeout，并持续响应显式取消。基础输出在截止时间内已保存后，补充超时允许继续本地发布基础记录：Runner 必须把“禁止新外部工作”与“允许发布已完成结果”分开，不在补充返回后用统一 `active()` 抛掉基础成果。模型 deadline 不延长；本地文件发布仍执行完整性与取消仲裁。

logical_call_id 固定为 `native.focus_response`。输入绑定基础摘要、关注点、输出语言、模型任务与当前 prompt/schema 版本；改变任一输入拒绝复用。正常调用与未知派发都计费：

| durable 状态 | 恢复动作 |
| --- | --- |
| 基础已保存，补充尚未 reserve / 未 dispatch | 复用基础结果，在原预算下允许一次补充调用。 |
| SDK 提议已保存，模块结果尚未保存 | 校验 adapter 的 prompt/输入摘要后恢复提议，不重新调用。 |
| 已 dispatch、响应未知且无合格缓存 | 记录 `response_unknown`，不重复派发。 |
| 已有 available / unavailable 补充结果 | 精确重放，不取数、不调用模型。 |
| 基础输出或身份/摘要损坏 | 明确失败，不重新解释历史结果。 |

模型返回错误、格式或引用不合法保存 `model_failed` / `invalid_response`。checkpoint/global store 损坏、预算身份冲突和显式取消不捕获为普通 supplement unavailable；遵循原错误语义。

## 5. 发布、读 API 与同源报告

基础 `publish_native_record` 仍是必需发布，失败不能完成运行。关注点有自己的 candidate、输入/内容摘要与 append-only 发布事件，graph task 为 `native.focus.final`。它只能在基础 public artifact 已 committed 后提升为 public artifact，且必须绑定该基础记录的 canonical 摘要与同一 lifecycle 授权。单独附加物发布错误不得回写或撤销基础 public artifact；非全局损坏错误允许基础运行完成，Reader 明确显示补充未发布。全局不可恢复存储错误仍为运行错误。

恢复时，已发布基础 artifact 必须与 frozen baseline 相同；已发布补充 artifact 必须与保存候选相同且绑定同一基础记录。不得用 checkpoint 草稿代替 committed 附加物向用户显示。

可选发布的最终处理写入独立 checkpoint 字段 `native_focus_publication`，绑定基础摘要与补充候选摘要，状态为 pending / committed / unavailable；committed 保存对应 artifact/event 身份，unavailable 保存稳定 reason_code。提升前先保存 pending；提升成功或局部失败后持久化最终处理。仅在失败处理可以 durable 保存、基础 artifact 完整时把局部发布错误降为补充 unavailable；不能持久化的全局错误仍失败。崩溃后先查已 committed 补充事件，精确校验后收敛处理状态，不重写已有 artifact；已保存 unavailable 不再隐式尝试提升。首次 Markdown 生成前完成处理状态，Reader 与导出使用同一最终状态及 event-sequence 边界。

新增只读 `GET /api/runs/{run_id}/reader/focus`，闭合 envelope 含 schema_version=1、run_id、source_sequence、state 与适用字段：

| state | 条件与返回 |
| --- | --- |
| `ready` | 基础/附加物均已 committed，身份、摘要、原始关注点与引用资格通过；返回 canonical response（包括明确 unavailable 的已保存回应结果）。 |
| `pending` | V6 有关注点且运行仍在执行/待发布；不返回提议。 |
| `unavailable` | 应有补充但发布失败、终态未发布、损坏或绑定不一致；稳定 reason_code，不泄漏原始异常。 |
| `not_applicable` | 没填写关注点、旧 V1–V5 或兼容 profile；reason_code 为 `focus_not_requested` / `legacy_question_semantics` / `unsupported_profile`。 |

缺 run 仍使用现有 404。投影在单一 event-sequence 边界校验基础 artifact、checkpoint 与补充 artifact；未知生产版本返回 unavailable，不能猜语义。读取始终不取数、不调用模型、不补写。

Reader 保留已交付阅读/证据交互，新 V6 首屏显示模式拥有的“研究范围”和“综合判断”。关键依据、主要疑点、下一步、实际核查、估值和市场背景仍属于基础研究。在基础报告末尾独立展示“补充关注点”，保留用户原文、回答/缺口及其引用入口；加注“基于已保存证据的补充回应，不改变上述综合判断”。未填写时不渲染该区。unavailable 显示具体状态，不能使用基础判断冒充回应。

旧报告仍按原始问题与回答呈现；过程可明确标识“历史版本：研究问题作为主任务”，不暗示已经拥有独立基线。002130 的原文件与内容摘要不变。V6 process 的 question_origin 指基础模式目标为 default，关注点来源单独为 user；不能仅根据 metadata.research_question 非空把基础目标标为用户问题。

Markdown 从同一已验证基础记录与 committed 附加物渲染：V6 使用基础研究标题与顺序，在末尾追加补充区；关注点 unavailable 原因同源展示。旧渲染/字节和已生成报告保持兼容。导出不执行模型、也不从运行草稿兜底。若可选附加物未成功发布，稳定缺失状态参与首次报告生成；之后不隐式改写已生成报告。

## 6. 角色、诊断与契约传播

V6 有关注点时增加 `native.focus_response`，显示“关注点回应”，明确它位于基础综合之后、没有参与原挑战；无关注点为 not_applicable，不制造一次模型运行。旧 V1–V5 保留六个 native 角色。注册已知 actor 与按保存版本/请求选择实际角色分开，更新 Runner、RunManager、运行角色 DTO、SSE、Audit 和 Reader Agent 页，不能直接给所有旧运行插入第七角色。

Reader 的 AgentKey 与闭合 proposal union 加入 focus_response。新角色可读其合格已发布 proposal 和引用；不暴露 prompt、原 SDK payload 或 checkpoint。基础 claim_origins 仍只来自原专项，补充引用不是基础作者归属。

计数分别展示主分析预算、补充回应预算、结构修复预算与 SDK 主/补充/修复授权；SDK total 包含补充。SDK observation 扩展必须保留旧覆盖的不确定性，未记录不能当 0，也不能把补充预算授权当作 SDK 发出证明。整次模型 total 的 12 次硬上限同时覆盖主、补充、修复与重试。

维护 `web/native_reader_versions.py` 的 V1–V5 冻结分区，V6 添加明确 policy（复用 V5 资格但不改变历史映射）；更新 process input/output 校验以识别新 kernel identity。来源政策版本与研究问题语义版本不能混为一项。

契约先从 Python schemas / execution models 改，再传播到公开 artifact 提升白名单、checkpoint/recovery、Web DTO/投影、`frontend/src/api/contracts.ts`、Reader/hooks/控件、报告和测试。现有 research-package 的基础 record 内容不变；需要补充回应的消费者使用新独立 public artifact/只读端点，不能把回应作为基础事实无标识并入。

## 7. 验证与验收边界

实施前再次查询项目约定并核对本地测试脚手架。新增测试验证信息隔离与失败语义，不用“提示词出现客观二字”代替行为证据：

1. 固定同一 V0 与 run_id，分别传无关注点、AI 关联、现金流、与证据无关及含指令注入的关注点。记录 collector 输入、三个专项、挑战、验证选择和基础综合 context/prompt；基础上下文、prompt 摘要与基础身份全部相等。固定 deterministic caller 的基础记录摘要相同。正常 run_id 不同的真实运行不要求 ID 或模型文字逐字相同。
2. 调用序列断言补充 reserve/dispatch 时基础输出已经 durable 保存；后置模块输入不含写基础接口；补充成功、失败或 malicious extra fields 都不能改变基础摘要。
3. 验证三模式及批量：公司现有三维度、催化 84 日、持仓原假设仍正确；填关注点不减少专项/挑战槽位、不改变来源和固定检查。相关证据自然涉及关注主题时仍允许独立分析。
4. 验证额度：无关注点零补充请求；有关注点最多一次 SDK、无修复/重试；总模型用尽/截止时间耗尽保存 unavailable，基础发布成功；显式取消不被吞掉。覆盖补充 dispatch 前、SDK 返回后、lifecycle 授权前后这些取消竞态断点：授权前取消胜出，授权后按当前 terminalizing 规则处理。验证 SDK 授权与预算计数分离。
5. 验证恢复：基础冻结前后、补充 dispatch 前后、SDK cache 与结果保存间、基础/附加物发布间中断；复用已用额度，未知响应不重派。校验 changed focus、base digest、prompt 和 unknown version 拒绝或明确降级。
6. 验证投影：跨 run/ticker/mode/cutoff、非法引用、来源时间、未 committed/corrupt/digest mismatch 被拒绝；所有读端点对模型/供应商零调用；损坏补充不使合格基础记录不可读。
7. 验证前端与 Markdown：V6 基础目标和完整判断优先，补充在后；真实状态、引用及新角色可达；切换运行不残留旧回应；无关注点/旧运行/不可用状态明确；原桌面证据/Agent 交互仍通过。沿用现有桌面范围，不新增视觉方案或手机验收。
8. 验证历史：V1–V5 读资格、prompt、恢复、budget、Markdown snapshot 保持；只读核对 002130 样本前后文件摘要不变。

执行相关 pytest（核心、SDK adapter、budget/checkpoint、publication、Web wiring/projections/reports）、Vitest 和现有桌面 Playwright。完成 root AGENTS 要求的 docs check、Ruff、npm ci/typecheck/build（含同步 static）、git diff --check 与 scoped status 核对。功能测试与合成结果仅证明隔离和操作链路，不证明研究准确性。

需要真实模型验证时，另行给出固定证据、最多请求数和比较标准供用户确认；未经确认不新建付费运行。002130 旧记录不能用来宣称新基线质量，因为旧专项已经受到关注点输入影响；可复用它的合格 V0 做新的有界对照，但不能把旧推断当作新独立分析。

## 8. 文档、实施顺序与完成标准

实施顺序：canonical focus/schema 与 V6 身份/预算 → 独立核心边界与冻结 → 后置执行/恢复 → 发布与读投影 → 控件/Reader/角色/Markdown → scoped 自动化与历史验证 → 当前文档同步。

交付时同步 README、ARCHITECTURE、docs/contracts/research-record.md、docs/architecture/research-reader.md、docs/operations/evidence-research.md 与 llm-reasoning.md，增加补充契约说明及必要 CHANGELOG，更新 docs/README.md 索引。历史 question-first 设计/验收作为日期记录保留，不反写为新语义；后续验收另写日期报告。

完成标准：新运行核心输入不可见关注点，基线先持久化，后置最多一次 SDK；补充引用可追溯且不能改基础结果；普通补充失败隔离，取消/完整性语义成立；预算、恢复、历史读取和全部受影响客户端通过适用验证。Git push、PR、merge、release 与额外真实付费验收不在本次规格阶段执行。
