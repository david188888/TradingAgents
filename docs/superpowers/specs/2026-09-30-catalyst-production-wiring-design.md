# 催化研究真实接线与显式试用

- 日期：2026-09-30。
- 状态：独立 spec reviewer 两轮审阅通过，用户已批准书面设计；显式接线已实施。本文记录批准时设计，当前行为见[操作说明](../../operations/catalyst-research.md)，实测限制见[验收记录](../plans/2026-09-30-catalyst-wiring-acceptance.md)。
- 基线：`main` @ `4f0fa11`，工作区干净。沿用 [原设计](2026-09-28-catalyst-research-redesign.md) 与 [最新交接](../plans/2026-09-29-engineering-handoff.md)，不重做 P0–P4。

## 1. 目标、范围与不变式

用户显式选择 `catalyst_v1` 后，实际运行冻结证据、三个专项、独立反证、单次综合、确定性校验和发布，并能在工作台读取本次运行的产物。单元测试证明模块行为，HTTP 与浏览器验证证明用户路径；二者单独都不能证明研究质量提升。

本轮完成执行分流、数据及模型适配、持久化与恢复、表单接入、工程验证及当前态文档。不进行 48 次批量 LLM 对照，不切默认，不推送或创建 PR，不清理历史 worktree 或用户数据。有限 live smoke 属接线验证，执行前公开实际模型配置与调用上限；不能把降级运行写成完整研究成功。

必须保留：

1. classic 为省略 profile 时的默认；既有 CLI、持仓复盘、长期研究、classic checkpoint 语义及指纹不变。
2. `catalyst-evidence-policy-v1` 不进入 horizon 专用 `RuntimePolicyVersion`。
3. 缺失覆盖、失败、限流、分页截断均不能成为“无事件”；历史 cutoff 下 qfq 资格未证实不能进入市场专项。
4. 读取、SSE 重连、页面刷新及投影重建不触发模型或 provider 调用。
5. 取消之后的迟到结果不能发布公开结论；重试创建新 run，恢复继续同一个 run 并继承预算。
6. 引用、身份、时点、反证 disposition 与优先级上限由代码校验；失败或不足必须保留明确原因。

## 2. 已核实的连接缺口

| 边界 | 当前缺口 | 本轮责任 |
| --- | --- | --- |
| 请求 | `RunCreateRequest` / `AnalysisRequest` 无研究问题；前端 builder 丢弃问题 | canonical 请求先扩展，再更新 API/TS/持久化/恢复 |
| 表单 | `CatalystForm` 无生产引用；“近 30/90/180/365 天”与原设计未来展望混淆 | 表单挂载，窗口呈现采用第 3 节语义 |
| profile | manager runner factory 一律创建 classic graph；snapshot metadata 无 profile | 创建、重试、恢复、读取全链路保留 profile |
| 模型 | workflow 只接受注入的 `ModelCaller` | 复用项目 LLM client factory 的 production adapter |
| 证据 | `EvidenceFreezer` 接受调用方提供的 `FreezeInputs` | 真实 fetch 编排及来源、覆盖和 PIT 校验 |
| 发布 | `CaseCommitter` 仅内存记录，不能证明重启后的幂等 | 持久化屏障、checkpoint 与正式产物事件 |
| 恢复 | 默认预检仅接受 classic `AnalysisRunner` | 独立 catalyst 恢复兼容性与执行前沿 |
| 报告/视图 | manager 走旧报告和辩论摘要路径 | catalyst 同源报告及阶段投影；不额外总结 |

前端 builder 当前还发送 `selected_analysts: []`，与 HTTP schema 至少一个 analyst 的校验冲突。接线必须验证真实请求体，不以组件渲染通过代替请求可执行。

## 3. 请求与时间语义

原设计 §4.1 / §7.1 已定义：研究窗口是**未来几周至一季度的研究展望，首版固定上限 84 个日历日**；历史证据回看是独立的 7/30/90 天事件及价格/财务窗口。

本轮复用固定 84 天 policy，表单展示“自研究截止日起未来最多 12 周”，移除把历史起止日期当作展望的快捷选项。暂不新增可变展望长度，以免改变 policy 及指纹契约。证据仍仅允许截止时已知的信息；未来事件只能引用已公开的安排，日期未知就保持未知。

新增可选 `research_question` 到 Python 中立请求与 HTTP schema，再同步 TS 请求 facade。沿用 canonical `CatalystResearchCase.research_question` 的 400 Unicode 码点上限，去首尾空白，空值归一为 `None`；前后端用同一边界 fixture（含 emoji），不能接受最终 case 无法序列化的请求。classic 不携带该字段，显式提交非空问题时拒绝，避免暗示 classic 会处理它。问题影响新角色上下文，并写入最终 case；不新增规划 agent。

窗口来自 policy，问题、cutoff、ticker、profile、policy、有效模型配置及 workflow 版本进入 catalyst 恢复身份。classic 的新增可选字段省略且 `profile_identity()` 仍为空，冻结指纹不因本轮变更而漂移。

新 profile builder 从自己的状态构造请求，不提交旧角色、轮数、horizon、holding 的用户选择；旧 wire 必需项采用服务端已定义的兼容默认。生产端校验空列表/缺省语义必须一致，最终以 API 实际接受的 canonical 请求为准。工作台有效配置摘要显示固定流程和实际模型，而非隐藏的 classic 深度。

## 4. 执行与适配边界

新增 consumer-neutral catalyst 执行适配，返回现有 `AnalysisResult`（signal 为 `research_only`）。Web manager 按 profile 选择 runner，保持 classic factory 原路径。中立 classic runner/facade 若收到显式 catalyst 请求，也必须分流到新执行适配或明确拒绝，不能运行旧 graph 冒充新 profile。公开支持范围仍是 A 股普通股票、公司研究。

执行适配协调三个职责分离的单元：

- 数据采集单元：调用现有 dataflows vendor 接口，将身份、公告/事件、财务、价格及能力结果转成 `FreezeInputs`，交给 `EvidenceFreezer`。来源、日期、单位、窗口资格和完整分页需要可核验；只有来源能证明的事实才进入 `qualified`。能力没有合格来源就输出 typed unavailable/unknown，不从文本猜测覆盖。
- 模型调用单元：复用 `create_llm_client` / provider 配置；专项和反证使用 quick 模型，综合使用 deep 模型，返回 workflow 要求的结构。请求显式提供输出形状及合法证据 ID；保留引用验证和单次结构修复。禁用 SDK 自动重试，由账本显式批准每次尝试，usage 未知保持未知。模型不获得数据工具，不能在预算外取数。
- 持久化执行单元：负责预算记录、角色结果缓存、阶段提交、恢复身份校验与最终发布。它依赖 runtime/observability，不导入 HTTP、SSE 或 React 类型。

数据能力调用与底层网络尝试必须分别计数；provider fallback、分页和重试均在调用前扣账。复用现有 provider 接口时，若无法观测实际底层尝试，就先增加必要的 instrumentation，再宣称预算有效。cache 命中与真实 dispatch 需区分，恢复不把未知调用当作免费。

保留 `BudgetLedger` 的代码默认上限（主分析 5、语义预处理 2、结构修复 2 且每阶段 1、网络重试 3、模型总尝试 12、数据能力 24、HTTP 尝试 64、专项并发 2、补取 1 轮/3 能力）。policy 中 20/40 是较宽的 ceiling，实际许可取 policy 与 ledger 的较严值。新增 adapter 不用 policy 数字扩大现有 workflow 预算。并行专项仍按 `ROLE_ORDER` 预留额度，模型调用保留并发。

承接原设计 §5.4–5.5：batch 与角色并发共同受 process-wide 模型/数据 semaphore 约束，等待时间和队列时间单独记录；每个线程显式传递 run 的 config/provenance ContextVar。活跃执行默认最多 300 秒，从调度执行开始计，不计排队；超时停止调度并禁止迟到发布。高级设置的显式 timeout 调整须持久化进恢复身份，不自行扩大默认上限。

## 5. 持久化、事件与恢复

每个 run 持有自己的持久化记录：恢复身份、冻结证据、预算账本、已完成角色结果和阶段状态。复用 run store 的原子 artifact 与 append-only event 能力；只有已提交记录可作为恢复前沿，不依赖进程内字典。新角色使用独立 registry，不冒充旧 analyst/lens，也不改变 classic registry 的角色集合。

catalyst 的 durable 阶段记录是执行及预算安全的一部分，始终启用；旧 `checkpoint_enabled` 只控制 classic LangGraph checkpoint，不用于关闭 catalyst 的持久化。catalyst 支持信息和恢复按钮依据其 durable 记录，不被旧 LangGraph 能力探测误判为关闭。若无法创建可靠的 durable store，拒绝启动而不是降为内存运行。

模型调用以逻辑调用 ID、prompt digest、attempt ID 标识。许可先持久化，再 dispatch；已得到的有效结果先持久化，恢复时按 identity/digest 复用。dispatch 后无结果的尝试保守计入已耗预算；恢复只在剩余额度内重试，不承诺远程计费 exactly-once。预算持久化失败时不 dispatch，角色结果持久化失败时不推进提交前沿。

阶段顺序固定：evidence → specialists → refutation → synthesis。阶段完成事实绑定对应输入/输出 artifact；角色候选与正式提交分开。现有事件 schema、reducer、审计及 TS 镜像按新角色更新，运行中 UI 从持久化阶段事实派生，不以自由文本猜测进度，不编造百分比。

恢复预检在重启 worker 前验证 fingerprint、artifact 哈希、run/ticker 身份和阶段依赖。profile/policy/问题/模型或 workflow 不兼容时返回稳定冲突，零模型/provider 调用；缺失或损坏 checkpoint 明确拒绝，不能降级成从头运行。新 run 的显式取消为终态，只允许 retry；可恢复中断继承历史额度。

最终公开 case 经 schema、预算和取消校验后，写入有 durable parent 的 `catalyst-research-case-v1` committed artifact 事件，复用公开产物发布机制。相同 run/相同内容再次发布为幂等；相同 ID/不同内容为冲突。持久化屏障和公开产物写入之间崩溃时，恢复只补发布，不重做模型调用。最终 `run.completed` 在正式产物和同源报告就绪后发生。迟到取消由单写者生命周期仲裁：若取消先获准，则候选不能变成正式结果。

公开发布授权与取消接纳共用 manager 的生命周期锁，授权的 committed 记录是发布线性化点。取消先到时拒绝提交；提交先到时进入不可取消的 terminalizing，允许完成原有产物与报告事务，取消请求返回已有终态/冲突，不能把已发布 case 后改为取消。对这两种顺序及屏障后崩溃分别注入 failpoint 验证。

Markdown/完整报告从已提交 canonical case 确定性生成；不运行 classic debate summary，不编造 classic 角色输出。`/catalyst`、摘要、详情与 Markdown 引用同一 case。失败/阻断有合法产物时展示质量和限制；没有正式产物时显示 unavailable，不能仅凭 `run.completed` 判断研究完整。

## 6. 页面接线与兼容

现有 classic controls 保留。显式切换 profile 后展示 CatalystForm、有效配置和研究问题，提交成功后选中本次 run；切回 classic 恢复旧角色选择但不泄漏到 catalyst 请求。retry 和 resume 由服务端保留原始 profile/问题/policy。

`useCatalyst` 在阶段事件及终态后刷新只读投影，跨 run 保持隔离。新流程使用四阶段进度与已完成的七行简报/证据抽屉；classic 使用原 legacy 读取。沿用 tokens 配色和共享焦点管理，重建 static 随源码交付。服务端支持标识只有 production runner 确实接入才宣称支持。

## 7. 验证与交付证据

先在同一棵树测基线，以测试名称和失败类型比较回归，不能拿历史失败数作替代；现有基线 12 个稳定失败及 1 个偶发项见交接说明。

本次设计阶段已在 `4f0fa11`（仅新增本设计 Markdown，未改代码）复测：15 failed / 2319 passed / 73 subtests，66.24 秒。12 项与交接稳定集合一致；额外 3 项是 `tests/web/test_web_cli.py` 中 launcher / explicit_open / runtime_failure，用例试图写 `~/.tradingagents/web/logs/server.log`，被本会话 sandbox 拒绝（同文件独立复测亦为 3 failed / 5 passed）。这些是当前受限环境的未通过检查，不宣称通过、不改测试掩盖；后续需使用合法的临时日志隔离方式或获准环境验证，避免触碰用户 run 数据。原始输出：`/private/tmp/catalyst-wiring-baseline-20260930.txt`。

Focused tests 必须覆盖真实边界：API 创建 → factory 选新 runner → 持久化产物 → `/catalyst`/报告读取；classic 不调用 catalyst；问题传递；snapshot 重载后 profile 不丢；预算紧张串并行等价；读/重连零调用；跨 run 隔离；每个阶段中断恢复、未知 attempt 扣账；同 ID 冲突；fingerprint 不兼容零调用；取消与发布竞态；provider 覆盖失败的保守降级；SDK 重试关闭与实际网络计数；隐藏配置不泄漏。

浏览器验证用真实本地 Web server 与隔离的临时 run store，mock model/provider 和 live smoke 分开记录。浏览器覆盖 1440×900、1280×800、390×844、200% 缩放、键盘/焦点/Esc、七行核心内容可读、状态矩阵、切换 run、重连及取消恢复。fixture 状态矩阵证明 UI，不当作 live 研究证据。

工程门禁：check_agent_docs、Ruff、pytest（失败集合不扩大）、前端 ci/typecheck/Vitest/build、适用的 Playwright、git diff --check。当前态 README/README.zh-CN/ARCHITECTURE/docs/CHANGELOG 同步实际支持范围；更新交接和验收记录。报告分已验证、失败、未验证，保留真实源不可用及历史 cutoff 资格限制。live smoke 的模型、调用次数、产物路径与降级事实留档，不声称完成 T33/T34 或质量/性能提升。

## 8. 顺序与停止条件

顺序：请求与持久化身份 → 生产 adapters 与 durable runner → manager 生命周期/恢复/报告 → 表单/事件/读取 → focused tests → 浏览器与有限 smoke → 回归及文档。

遇到产品语义不在原设计内、需要扩大付费运行范围、改变 classic/default、或 provider 无法证明关键资格时，报告证据并请求必要决定。来源不可用本身走已定义的保守降级，不阻塞实现；无法满足硬预算或发布/恢复不变式则不得启用显式入口。
