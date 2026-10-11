# 可回放运行记录（安全边界）

- **Status: Current**（current-state 文档；运行时行为变化时对照 `tradingagents/observability/` 与 `tradingagents/execution/` 校验）

每个本地分析 run 的目录可以包含三类互补记录：

- `events.jsonl`：版本化、追加式的生命周期事件，是状态和 SSE 回放的权威来源。
- `scratchpad.jsonl`：安全的调试标记流。每条记录只保留事件类型、稳定哈希、artifact 引用和少量数值元数据，并用 `event_id`/`event_sequence` 关联到 `events.jsonl`。
- `cycle-record/<sha256>.json`：单个 `CycleRecord` artifact，冻结该轮 query、非机密 spec 快照、事件范围和报告/scratchpad 引用，用于审计或离线 replay。

## 安全规则

`scratchpad.jsonl` 不是模型思考文本的存储位置。它不得持久化私有推理链、prompt、原始工具参数或原始工具结果；这些值仅被清洗后计算 SHA-256，并可指向已经过红化处理的 artifact。`thinking` 事件只表达 `private_reasoning_not_persisted`，因此可在回放中说明边界，而不会泄露模型内部推理。

当前注册的 scratchpad 生命周期事件为：`tool_limit`、`thinking`、`microcompact`、`compaction`、`context_cleared`。调用方应使用固定的 `detail_code` 和安全的计数/状态元数据，而不是任意文本。

## 原生模型失败诊断

新发生的原生模型失败会在 durable checkpoint 的
`native.model_diagnostics` 中按阶段和 `main` / `repair` 分开记录。
`execution/native_model_diagnostics.py` 拥有安全元数据的生成规则：区分请求、
配置、JSON、schema 与代码引用校验；只保留固定错误类别、声明的字段路径、
数值 HTTP 状态、允许的上游错误码和结束原因。未知字段名会被替换，
不保存响应正文、校验输入、任意异常消息或模型推理文本。

诊断不放宽研究校验；诊断本身不新增模型请求。
历史 checkpoint 没有该字段时，不能回填或推断其具体失败原因。
ChatGPT 的账户/用量操作提示仍使用单独的 `native.model_failures`。

## 原生模型有限网络重试

新建 V6 研究在恢复身份中冻结 `model_retry_policy`（`native-network-retry-v1`）。
首次请求后最多重试三次，间隔依次为 2、5、10 秒；只处理明确的连接/超时
错误、HTTP 408、429 与 5xx。已识别的凭据、参数、上下文或额度错误不重试；
JSON/schema 错误仍走原有结构修复。V6 可选关注点回应保持一次调用、不重试。

ChatGPT 订阅仅对普通 HTTP 408/429/5xx 使用上述有限重试；计划额度、权限、
能力、协议错误及未完成流不重试。它的 Responses 客户端每次 invoke 只发
一次请求，不换账户、模型或计费。历史无策略运行保留原零重试语义。

每次重试先预留 `network_retry` 再持久化发出授权，计入 `model_attempts`。
整条研究共用三次网络重试、十二次模型请求上限，因此单个调用可能因共享
预算先耗尽而提前结束。结构修复请求本身的临时失败也可使用这份网络预算。
等待期间不占全局模型并发槽，并持续检查取消与截止时间；未发出的预留会
释放，已发出但没有 token 测量的请求保留未知用量，成功重试的 token 不会
重复计入原请求。SDK 自动重试仍关闭。

`native.model_attempt_diagnostics` 保存逐请求的安全失败元数据；
`native.model.<stage>.<main|repair>.retry.<1..3>.dispatched` 保存实际重试授权。
Reader 的 `sdk_main` / `sdk_repair` 分别包括对应来源的重试，`sdk_total`
与 Audit 因此包括全部可观察请求。授权不证明上游接收、成功或计费。

历史身份没有该策略时保持原有行为；未知/崩溃中的旧请求仍不能自动重放。
这项重试不补数据，也不把合法输出或已完成运行等同于研究质量通过。

## 当前范围

系统已提供 `DurableRunObserver.record_scratchpad(...)` 和 `record_cycle(...)`，供执行、上下文压缩与工具限额路径调用。CycleRecord 与 JSONL 均为本机文件系统审计功能；它们不上传，也不替代真实供应商/LLM 端到端评估。评判模型与目标模型隔离、contradiction 一票否决数据集及 source-alignment 投影仍需在对应评估路径接入。


## V7 reply observations

The saved workflow selects the native role registry. V7 inserts operating/event/market response roles before synthesis; V1–V6 do not gain these roles. A targeted specialist replies once (multiple assigned challenges share a call); no target makes the role not applicable with zero actual dispatches. Replies use main budget (V7 ceiling eight), optional focus remains separate (one), and all SDK attempts, repairs and retries share twelve. Counts remain authorization counts, not delivery or billing evidence. See [unified company research](../contracts/unified-company-research.md).
