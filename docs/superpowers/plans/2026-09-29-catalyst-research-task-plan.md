# 催化研究重构：任务拆分与验收计划

- **Status: Proposed — 执行计划，尚未实施。所有 TODO 均为待办，不代表已完成。不要把本文件作为当前实现行为的证据。**
- 创建日期：2026-09-29。上游设计：[催化研究重构设计](../specs/2026-09-28-catalyst-research-redesign.md)（以下简称「设计」）。交互草图：[布局 A](../specs/2026-09-28-catalyst-research-layout.html)。
- 代码基线：`bc70a35`。执行前由 P0 的 T01 重新确认。
- 本文件只做一件事：把设计的 T01–T39 拆成可分派、可验收、可独立完成的工作单元，绑定到 8 个交付 agent。
- 设计的决策、语义与门槛以设计文档为准。本文件不重复定义语义，只定义「谁做什么、怎么算做完」。

## 阅读导航

- §1 拆分原则与执行方式；§2 依赖图；§3 八个 agent 职责；§4 T01–T39 逐项验收；§5 跨 agent 契约交接；§6 全局硬性门槛；§7 命令与报告。

## 1. 拆分原则与执行方式

### 1.1 拆分依据

任务按**交付物**切，不按技术栈切，也不按设计的 P 阶段切。理由：设计的 P1–P5 是排期顺序，不是依赖拓扑——P4 前端可以靠 P1 的 fixture 与前端镜像先行开工，P2 的数据适配与 P3 的 graph 各自独立。切在交付物上，agent 的上下文才完整（读懂「一个 canonical schema + 它的全部生产者/消费者」需要跨文件视野）。

| 交付物 | 覆盖设计任务 |
| --- | --- |
| A. 基线与探测 | T01–T06 |
| B. 请求契约与版本 | T07、T10–T12 |
| C. 催化产物 schema | T07–T09（schema 侧） |
| D. 行情与事件数据 | T13–T18 |
| E. 有界研究流程 | T19–T25 |
| F. 工作台页面 | T26–T32 |
| G. 评估与默认切换 | T33–T39 |
| H. 数据源探测执行 | T04、T16（跨 D 的实测） |

### 1.2 为什么是 8 个而不是 5 或 39

- 少于 5 个：单个 agent 上下文要装下 schema + graph + 前端 + 验收，超长且难以并行。
- 多于 8 个：跨切分的契约（schema ↔ TS wire ↔ 投影）会被切碎，同一个字段在两处独立命名。
- 39 个：每个 agent 都要重新读 740 行设计并重建全局依赖认知，返工成本高于并行收益。

### 1.3 执行方式

- 每个 agent 一个 git worktree（`.claude/worktrees/<agent-id>`），从 `main`@`bc70a35` 切出，完成后由主会话合回。worktree 之间不共享工作副本。
- agent 内部串行推进自己负责的 T 编号，不自行扩展到其他 agent 的范围（设计的 §15：越界改动是主要失败原因之一）。
- agent 之间通过 §5 的契约交接表对齐，不直接改对方负责的文件。
- 任何 agent 遇到「需要改别人负责的文件才能继续」时，**停下来在交付报告里写明阻塞点**，不自行修改。

### 1.4 授权边界（2026-09-29 用户确认）

| 允许 | 不允许 |
| --- | --- |
| 真实行情/公告/财务端点探测（T04、T13–T16） | LLM 批量评估运行（设计的 §13.2 的 48 次对照） |
| 本地运行 pytest / Vitest / Playwright | 提交、推送、创建 PR |
| 写入自己 worktree 内的代码与文档 | 修改 `classic` profile 的既有语义 |
| 按 §6 门槛自查 | 切换 Web 默认入口（仅 G agent 在 §6 全过后提议，需你确认） |

LLM 评估运行的设计在 `tradingagents/` 之外无成本记录，48 次运行的模型预算需按实际模型价格单独核定，本轮不执行。

## 2. 依赖图

```text
P0 基线与探测 (A)  ──────────────────────────┐
        │ T01 HEAD / T02 案例集 / T03 篇幅    │
        ▼                                     │
B 请求契约与版本 ◄── T01 现状核查              │
  │  T07 profile/policy/schema 命名           │
  ├──────────────┬──────────────┐             │
  ▼              ▼              ▼             │
C 催化产物 schema  F 工作台页面   D 数据能力     │
  │  T08 invariants │  T10 TS   │ T13-T16     │
  │  T09 产物发布读 │  T26-T32  │             │
  └──┬─────────────┴────────────┴─────────────┘
     │            (P1 可用 fixture 解锁 F)
     ▼
E 有界研究流程 (T19-T25)  ◄── D 的冻结底稿能力
     │  T24 commit barrier / 恢复
     ▼
G 评估与切换 (T33-T39)  ◄── 全部
```

**关键解锁点**：C 完成 T08/T09 的 schema + fixture 后，F（前端）即可开工，不必等 E。F 使用真实 schema 镜像的 fixture 做契约测试，真实联调在 E 完成后补。这是缩短日历工期的主要手段。

## 3. 八个 Agent 职责

每个 agent 拿到：设计的相关章节 + 自己负责的 T 编号 + §4 的验收标准 + §6 的硬性门槛。

| ID | 名称 | 负责 T | 主文件区域 | 交付物 |
| --- | --- | --- | --- | --- |
| A | baseline | T01–T06 | `docs/superpowers/plans/`、`docs/operations/` | 基线 manifest、案例集、能力可用性矩阵、评估表 |
| B | contracts | T07、T10–T12 | `tradingagents/execution/models.py`、`web/schemas.py`、`runtime/fingerprint.py`、`frontend/src/api/` | profile 校验、TS wire 镜像、版本判别、fixtures |
| C | schema | T08、T09（schema 侧） | `tradingagents/agents/schemas/` | 催化产物 canonical schema、invariants、发布/读取 |
| D | data | T13–T18 | `tradingagents/dataflows/`、`research/` | 腾讯 raw/qfq adapter、事件标准化、冻结底稿 |
| E | workflow | T19–T25 | `tradingagents/graph/`、`agents/`、`observability/` | 三专项 + 反证 + 综合的 graph 与预算 |
| F | web | T26–T32 | `frontend/src/` | 单栏工作台、三标签、抽屉、状态矩阵 |
| G | acceptance | T33–T39 | 全仓（只读为主）、`README`/`ARCHITECTURE`/docs | 对照评估、验收报告、默认切换提议 |
| H | probe | T04、T16 | 只读 + 探测记录 | live 端点探测记录与 provenance |

**A 与 H 的边界**：A 定义探测清单与判定标准（设计的 §8.6），H 执行实测并出记录。H 的实测结论是 A 的 T04 验收输入，也是 D 的 T13–T16 输入。A 不直接调端点，H 不定义标准。

**B 与 C 的边界（2026-09-29 代码核查后细化）**：两者都涉及 T07/T08/T09，按文件所有权切：

| 归 B（请求契约与版本） | 归 C（催化产物 schema） |
| --- | --- |
| `research_profile` 请求字段与校验 | `catalyst-research-case-v1` canonical 模型 |
| `catalyst-evidence-policy-v1` 的**版本常量与窗口参数** | schema 层对 policy 值的引用 |
| 稳定错误码、预算字段的定义位置 | 全部 invariants 与负向测试 |
| TS wire 镜像（`frontend/src/api/contracts.ts`） | 产物写入与 `/catalyst` endpoint 的 schema 侧 |
| 5 类 fixture 文件 | schema 序列化往返测试 |
| 指纹/恢复的**兼容性判断** | 引用完整性、时点、优先级上限的**实现** |

**共享文件 `tradingagents/web/api.py`（2026-09-29 执行中补充）**：B 与 C 都会改它，但落点不同——B 接入 `research_profile` 请求校验与 policy 常量（T07），C 注册 `GET /api/runs/{run_id}/catalyst` 路由与 projection 导入（T09）。合回顺序固定为 **B 先、C 后**；C 不得改动 B 加入的校验分支，B 不得改动 C 加入的路由。若两边都新增了 import 块，合回时需人工确认无重复导入。

两者共享 `tradingagents/execution/models.py` 时，B 先改、C 后改，C 完成后 B 负责把 TS 镜像对齐到最终 schema。**C 不得改 `execution/models.py` 或 `web/schemas.py`；B 不得在 `agents/schemas/` 下新增或修改模型。**

**policy 版本的硬约束（代码核查确认）**：`tradingagents/runtime/contracts.py` 的 `RuntimePolicyVersion` 是 **horizon 门控专用**枚举，目前只接受 `horizon-policy-v2` / `horizon-policy-v3`。该字面量被 **5 个文件**消费：`runtime/contracts.py`、`runtime/fingerprint.py`、`execution/runner.py`、`observability/canonical.py`、`research/analysis_cutoff.py`。**禁止把 `catalyst-evidence-policy-v1` 加进这个 Literal** —— 新 policy 走独立的 policy 模块与字段，不复用 horizon 的 runtime contract 通道。这一条对应设计 §9「不得因为命名相近启用项目中已有的测试门控 horizon-policy-v3」的警告。

**G 的特殊约束**：G 只能在 A–F 全部交付且 §6 门槛自查通过后启动，且不自行切换 Web 默认（设计的 §11.2 第 3 步 + 你的确认制偏好）。G 的 T33–T35 涉及 LLM 运行，按 §1.4 授权，本轮标记为「待授权执行」。

## 4. T01–T39 逐项验收

验收标准的写法：**可复现的检查动作 + 明确的通过判据**。避免「应该可用」「基本正确」这类不可判定表述——这是设计反复强调的失败模式。

### A — 基线与探测

- [ ] **T01 基线 manifest**
  - 记录：HEAD sha、Python/Node 版本、依赖树、模型 ID、有效配置摘要（**不得含密钥**）、环境变量键名（不含值）、已有失败测试清单、平台。
  - 验收：`docs/superpowers/plans/baseline-manifest.md` 存在；`git rev-parse HEAD` 与文中一致；对该文件跑 `git diff --check` 无空白问题，且人工确认无 `sk-` 前缀、无 16 位以上疑似 token 字面量、无带 token 的 URL；失败测试清单可由 `python -m pytest --collect-only -q` 复现。
- [ ] **T02 案例集**
  - 选设计的 §13.2 的 12 案例（C01–C12），每例记录：ticker、cutoff date、场景标签、必须检查项、**可重放输入的保存位置**。
  - 验收：`docs/superpowers/plans/eval-cases.json` 存在且 12 条齐全；每条 `cutoff <= 2026-09-29`；每条有 `replay_input_ref` 指向仓库内可重放数据（无凭据）；无一条使用 cutoff 之后才发布的信息作为「历史事实」。
- [ ] **T03 篇幅与重复测量**
  - 测：首屏可见字符数、重复字段、首次找到关键问题耗时、每 run 的 LLM 调用/耗时/token，token 缺失记 `unknown` 不记 0。
  - 验收：`docs/superpowers/plans/baseline-readability.md` 含 ≥3 个真实 run 的测量表，每行有 run_id、字符数、重复字段清单、token 字段含 `unknown` 标记；至少 1 个 run 有 `unknown` usage 记录（证明没有把缺失当 0）。
  - **已交付的实测结论（2026-09-29）**：首屏正文 p50 **8,399 字符**（min 196 / max 14,599），对 420 硬上限超出 **20x**，15 个 run 中 14 个超限；`view.brief` 与 `learning_summary` p50 重叠 **96%**；LLM 调用 **20.6/run**（14–26）。token **可测**，但**不在 `run.json`**，而在 `events.jsonl → payload.usage`（嵌两层）——按 `run.json` 平面检索会误判为「不可测」。存在真实 `unknown`：5 个 failed run 各有 1 次 `model.started` 无 `model.completed`（成本已发生但未记录），其中 1 个 failed run 消耗 419,932 tokens。**另注**：15 个 run 中 8 个宏观数据源不可用，跨 run 比较内容质量时必须把它作为受控变量（T06 已据此设计）。
- [ ] **T04 探测清单定义**（标准由 A 定义，实测由 H 出）
  - 定义：每项能力需覆盖的维度（沪/深市、正常、无匹配、停牌/新上市、历史 cutoff、限流/超时、字段缺失、分页截断）与记录字段。
  - 验收：清单文件含 ≥10 项候选能力 × ≥8 个维度矩阵；每项有成功/降级/失败三态定义；明确写出「北交所未声明支持则精确标不支持」。
- [ ] **T05 隐含调用审计**
  - 审：现有 Evidence Steward 的模型调用点、SDK 自带 retry、source fallback 链、rate limit 语义。
  - 验收：`docs/superpowers/plans/hidden-llm-audit.md` 列出每个隐含 LLM 调用点（文件:行号）、retry 行为、fallback 顺序；每项标注是否会绕过设计的 §5.5 预算；给出预算计数器方案建议。
- [ ] **T06 评估表冻结**
  - 固定：严重错误定义、评分表（设计的 §13.4 四项 0–2）、性能目标、案例通过判据。
  - 验收：文件含变更记录区且当前为空；评分规则在看到新结果前冻结——若后续调整，验收记录里必须同时存在「调整前规则」与「调整理由」两版。

### B — 请求契约与版本

- [ ] **T07 profile 校验与 policy 版本**
  - 做：`research_profile: classic | catalyst_v1` 加入共享请求并进入有效配置与指纹；新建 `catalyst-evidence-policy-v1`（**独立文件，版本字符串与 `horizon-policy-v2` 不同名也不同义**）；稳定错误码与预算字段。
  - 验收：`RunCreateRequest` 有 `research_profile` 字段且 `extra="forbid"` 下旧请求仍通过（回归：现有 `tests/web/test_api.py` 全绿）；`catalyst-evidence-policy-v1` 独立存在；测试覆盖：缺省→classic、`catalyst_v1` + `holding_review`→明确拒绝而非静默切换、`catalyst_v1` + 非 A 股→拒绝、`catalyst_v1` + 非默认旧调度参数组合→可读校验错误；校验失败时**未入队、未扣预算**（断言 run store 无新记录、预算账本无扣减）。
- [ ] **T10 TS wire 镜像**
  - 做：前端 `contracts.ts` 镜像新字段与判别联合类型；版本路由。
  - 验收：`npm --prefix frontend run typecheck` 通过；新增 fixture 测试覆盖 `ready | unavailable | unsupported` 三态与旧 legacy 形状；**grep 断言无 `any` 用于绕开差异**（`grep -n ': any\|as any' frontend/src/api/contracts.ts` 无命中或每处有注释豁免）。
- [ ] **T11 Fixtures**
  - 做：最小完整、partial、blocked、unsupported、旧记录五类 fixture。
  - 验收：5 个 fixture 文件存在且能被 pytest 与 Vitest **同时**加载（同一份 JSON，Python 与 TS 各自反序列化）；每个 fixture 带 schema version 字段；`unsupported` 与 `unavailable` 的形状不同（断言不混淆）。
- [ ] **T12 指纹与恢复兼容评审**
  - 做：把 profile / policy / state / prompt / budget 纳入恢复兼容判断；产出评审记录。
  - 验收：评审文档回答「读者升级是否要求重算」（必须为否）；测试：指纹不匹配时拒绝恢复到不同拓扑并保留原记录（沿用 `tests/web/test_checkpoint_frontier.py` 的既有风格新增用例）；旧 checkpoint 指纹匹配时按原 profile 恢复。

### C — 催化产物 schema

- [ ] **T08 Schema invariants**
  - 做：实现设计的 §7.3 的 canonical Pydantic 模型 + 验证器。
  - 验收：以下断言各有测试且**故意破坏时失败**（负向测试必须存在）：ID run 内唯一；所有依赖可解析；推断必须依赖存活事实；未知不带虚假证据或置信度；数值有单位与期间；无依据日期保持未知；引用剔除后递归检查依赖；简报不得引用被剔除发现；**简报字符数上限 420 且溢出走受限模板而非截断**。
  - 关键：字符计数用 Unicode 字符、排除导航/字段标签/公司名/时间元数据，**前后端共享同一组测试样例**（同一 JSON 输入，两侧断言同一数字）。
- [ ] **T09 产物发布与读取**（schema 侧）
  - 做：`catalyst-research-case-v1` 写入挂在现有 graph commit barrier 之后；`GET /api/runs/{id}/catalyst` 判别式响应。
  - 验收：响应形状 `ready | unavailable | unsupported` + version 字段；run 不存在→404；run 存在未发布→200 `unavailable` + 新原因码；classic run→200 `unsupported`；已提交阻断报告→200 `ready` + completeness=blocked + 优先级信息不足；**endpoint 读取触发 0 次 LLM、0 次 provider 调用**（spy 断言）；内部异常不泄露原文（断言响应体不含异常类名/message）。

### D — 数据能力

**D 同时承担两项现存生产缺陷的修复**（2026-09-29 用户确认一并处理）。这两项不是新功能的输入，而是当前就在影响每次运行的缺陷：

- [ ] **T-D1 修复 mootdx 首位空转**
  - 现状：`dataflows/registry.py:271` 中 mootdx 是 A 股行情链首位，但 live 探测 13/13 用例失败——TCP 可连、`Quotes.factory()` 在 3 个服务器成功，**数据调用返回无列空 DataFrame**。每次行情请求先浪费约 26 秒再 fallback 到 Tushare。
  - 要求：把 mootdx 移出首位，或加快速熔断（首次空返回即标记该服务器不可用并冷却），使失败不再消耗每请求 26 秒。
  - 验收：有一个测试证明**连续两次请求的总耗时不因 mootdx 显著增加**；mootdx 在链中的位置变更或熔断逻辑有对应测试；`registry.py` 的顺序变更有 diff 证据。
  - **不得**顺手删除 mootdx 的财务/F10 能力（设计 §8.2 明确「不直接删除全部 mootdx 财务/F10 能力」）。

- [ ] **T-D2 修复腾讯 kline 列序**
  - 现状：腾讯 kline 实际列序为 `[date, OPEN, CLOSE, HIGH, LOW, VOL]`，**索引 2 是收盘、3 是最高、4 是最低**，非标准 OHLC。已由 4 只股票 × 28 天 max/min 不变式 + 与实时行情快照 4/4 字段精确比对双重证明。按 OHLC 读取会**静默得到错误的高/低价且不报错**。
  - 要求：修正解析，并加不变式断言（`high >= max(open, close) >= min(open, close) >= low`）作为回归防线。
  - 验收：存在一个测试对多只股票多日数据断言该不变式；**该测试在修正前必须失败**（证明它能捕获此缺陷）；所有消费腾讯 kline 的调用点均已核查。

- [ ] **T13 腾讯 raw/qfq adapter**
  - 验收：raw 与 qfq **各自独立** adapter 与测试文件；断言两者结果不混拼（qfq 不可用时 raw 不顶替）；覆盖沪/深、正常、无匹配、停牌、新上市、历史 cutoff、限流、字段缺失、分页截断 8 维；**每个测试带 provenance 记录**；单位、复权口径、截止时间、最后完整交易日均有断言。
  - **额外断言（T01 实测发现）**：`dataflows/interface.py:271-276` 在命中 vendor cooldown 时会把整条 fallback 链追加进来，其源码注释明写「even when the user explicitly selected one primary」。这与设计 §8.5「不因一个源失败强制更换用户显式选定的供应商策略」相反，且会让 raw 结果顶替 qfq。T13 必须为此写一条**显式反例测试**：显式选定 qfq 且 qfq 处于 cooldown 时，raw 不得静默顶替。
  - **实测结论（2026-09-29 探测，完整记录见 `docs/superpowers/operations/capability-probe-2026-09-29.md`）**：
    - **腾讯 kline 列序不是 OHLC**（最高优先级）。实际为 `[date, OPEN, CLOSE, HIGH, LOW, VOL]`：索引 2 是收盘、3 是最高、4 是最低。已由 4 只股票 × 28 天的 max/min 不变式 + 与实时行情快照 4/4 字段精确比对双重证明。按 OHLC 读取会**静默得到错误的高/低价且不报错**。T13 必须按真实列序解析并写断言。
    - **腾讯 qfq 会静默降级为不复权**：部分标的（688981、两个北交所代码）HTTP 200 但返回未复权 `day` 数据，无任何警告。必须判为 `unavailable`，**绝不可当 qfq 使用**。
    - **腾讯分页有静默截断**：640 行上限，无 total/count/more 标记；`count>=2100` 返回 `param error` 且 `code:0`。截断必须显式识别，不得当作「无更多数据」。
    - 腾讯 raw 与 qfq 对「当日未完成 bar 是否包含」处理不一致。
    - 腾讯估值快照可用（沪/深/科创/创业/北交所），含陈旧检测。
  - **PIT 约束（关键）**：Wind 与腾讯同属「qfq to today」anchor，最新 bar 天然等于 raw，**故最新交易日窗口内 raw 与 qfq 不可区分——这不等于 qfq 正确**。设计 §8.5 要求历史 cutoff 必须有复权因子/版本快照，否则标 `pit_unverified`。H 实测仅证明同一 session 内稳定，**跨公司行动稳定性未测**。T13 在补齐因子快照能力前，**历史 cutoff 的 qfq 不得进入市场专项上下文**。
  - **复权口径分歧（断言要求）**：Wind 与腾讯的 qfq 比值逐日变化（0.99556 → 0.99503），anchor 一致但**复权因子算法不同**，两源 qfq 值**不可互换、不可混用**。T13 须写断言防止同值化。
- [ ] **T14 业绩预告/快报事件**
  - 验收：官方披露为事实锚；结构化列表仅作发现入口；测试覆盖预告区间 / 快报 / 正式报表三态区分；预告区间**不取中点**；报告期与发布时点分离；cutoff 后发布的公告被过滤。
- [ ] **T15 回购/增减持执行链**
  - 验收：先输出与现有 insider trades 的字段对照表；只补计划/变更/实施/完成/终止链；测试断言计划≠已完成、主体一致、状态变更不重复计为两个利好。
- [ ] **T16 机构调研**
  - 验收：有证据价值则接入；端点不合格则**显式延后并在报告中写明**，不阻塞其他能力；管理层表述**不升级为订单事实**（测试断言该推断被门控拒绝）。
- [ ] **T17 事件去重与冻结底稿**
  - 验收：确定性去重（证券身份 + 公告/事件标识 + 时间 + 内容指纹）；语义聚类仅作有预算辅助；转载连到原始来源家族（测试：3 站点转载同一公告→**1 个来源家族、1 个事件、独立支持数不增**）；PIT 过滤；冻结底稿；**预算内至多一轮补充（≤3 能力）**，冻结后不可自由检索。
- [ ] **T18 异常与边界测试**
  - 验收：空值、无事件、限流、超时、部分分页、历史日期、证券身份冲突 7 类各有测试；**源失败不得被吞成空数据**（断言源失败时 capability 为 unavailable 而非「无事件」）；查询无结果区分「完整覆盖且无匹配」/「不支持/失败/限流」/「分页截断」三态。

### E — 有界研究流程

- [ ] **T19 三专项输入视图与输出**
  - 验收：三个专项各自独立输入视图，**仅消费冻结底稿**；测试断言专项 A 无法读取专项 B 的草稿；结构化发现每角色 ≤3 核心发现 + ≤3 未知；**严重质量错误不受条数限制但汇总进门控**。
- [ ] **T20 隔离、汇合与预算**
  - 验收：按角色 key 分区的不可变输出（**不并发写共享 messages/sender/拼接字符串**）；汇合按固定角色顺序读取（测试：打乱完成顺序，结果不变）；并发上限 2，串行降级上限 1 且**不改变结论语义**（串并行公共产物逐字相同的测试）；全局 LLM/数据源信号量（断言不会按 batch×角色 放大）；预算原子扣减（并发测试无超发）。
- [ ] **T21 独立反证与 disposition**
  - 验收：反证读发现列表而非高优先级结论（测试断言锚定被打破）；每条 challenge 都有 disposition（接受/部分接受/以证据反驳/无法解决）；**关键 unresolved 限制最终优先级**（validator 拒绝「优先核查」）。
- [ ] **T22 综合与确定性校验**
  - 验收：综合**不调用第二个摘要模型**；逐项处理 challenge；首屏/详情/Markdown 从**同一个 case** 渲染（三者引用 ID 一致性断言）；priority 上限矩阵（设计的 §9.1）逐行有测试。
- [ ] **T23 Evidence Steward 拆分**
  - 验收：可复用门控与有副作用 enrichment 分离；**所有隐含模型调用计数**（T05 清单逐项对应）；新 profile 冻结后**不从自然语言报告重建事实**。
- [ ] **T24 Commit barrier 与恢复**
  - 验收：产物写入在 commit barrier 之后；SSE 重连**不重复模型调用、不重复产物**（测试：重连后 LLM 调用计数不变）；恢复继承已消耗额度（**不从 0 重置**）；取消/超时后不发布迟到结果为最终结论；重复提交幂等、同 ID 不同内容报冲突。
- [ ] **T25 classic 回归**
  - 验收：测试断言旧多空辩论、持仓复盘、长期研究路由未被替换；旧角色 key 与 lens 枚举仍服务旧 profile。
  - **判定标准（2026-09-29 实测基线修正）**：`python -m pytest -q -p no:randomly` 在 `ca90f27` 上为 **15 failed / 1983 passed / 73 subtests**，明细见 `docs/superpowers/plans/baseline-pytest-failures.md`。基线本身**不是全绿**，因此通过条件是「失败集合不扩大、且这 15 项状态不变」，而非「全绿」。
  - **高风险区**：`test_runtime_scaffold.py` 的 3 项（`test_production_v2_descriptor_and_delta_are_frozen`、`test_production_v2_fingerprint_bytes_are_frozen`、`test_checkpoint_authorization_is_bound_to_prepared_context`）**已经是红的**，且正是 B/E 改 profile、policy、指纹时会碰的地方。B 动 `runtime/fingerprint.py` 前后必须分别记录这 3 项的状态，否则无法区分既有问题与自己引入的。

### F — 工作台页面

前置：依赖 B 的 T10/T11（TS contract + fixture）与 C 的 T08（schema）。真实联调依赖 E。

- [ ] **T26 布局重组**
  - 验收：`WorkbenchLayout` 完成页**只有一个主摘要容器**（组件测试断言主摘要元素数量 = 1）；三标签（研究简报 / 依据与事件 / 研究过程）；历史侧栏可收起；更多研究入口可达。**配色沿用现有 `frontend/src/styles/tokens.css` 设计变量，不复制草图的 `#f5f4ef` 等色值**。
  - **去重对象已由 T03 实测确定**：真正并列渲染、p50 重叠 96% 的是 `reader-brief-v1.json.learning_summary` 与 `run-view-v1.json.view.brief`。设计 §3 提到的 `executive_summary` / `drivers` / `risks` 在 15/15 个真实 run 中**全为 null**（`executive_summary` 非 null 计数 0/15），去重**不能靠删除这些投影字段**——它们不承载内容。T26 的组件测试应断言前两个容器不再同时挂载。
- [ ] **T27 表单与配置**
  - 验收：默认表单只显示公司、窗口、可选问题、开始按钮；profile 切换显示有效配置摘要；**不自动提交隐藏配置**（测试：切换 profile 后请求体不含旧的隐藏字段）；旧模式切换保留原角色选择。
- [ ] **T28 首屏五项**
  - 验收：判断 / 优先级 / 最多 1 主催化 / 最多 3 依据 / 至少 1 疑点 / 下一验证 / 关键限制七行全部渲染（与设计的 §4.3 表逐行对应）；**超长走 ≤120 字安全模板 + 默认展开的完整限制列表**，不截断（测试：多风险 fixture 下最后一条风险仍可见）；依据可点开追溯。
- [ ] **T29 证据抽屉**
  - 验收：桌面按需抽屉、窄屏弹层；焦点管理、Esc、背景 inert、返回位置四项各有测试（**复用并验证现有 Companion/Audit 的可访问性逻辑**，不重写）；**不同 run 的证据不串到同一抽屉**（测试：切换 run 后抽屉内容换新）；无合法公开链接时显示来源标识与限制，不暴露内部 locator。
- [ ] **T30 运行中与终态矩阵**
  - 验收：四阶段进度（准备证据 → 专项分析 → 反证核验 → 综合发布）；**无准确工作量时不显示百分比**（测试：无工作量数据时不渲染 % ）；八种终态（设计的 §4.5）各有渲染用例；取消/重试/恢复/SSE 重连语义保留；未提交流式候选显示为处理中，不显示为最终结论。
- [ ] **T31 旧 run 分层读取**
  - 验收：旧 run 走「概要/详情/过程」分层，**不产生新研究优先级**（测试：旧 run 响应无 priority 字段）；持仓、批量、审计入口可达。
- [ ] **T32 响应式与可访问性 + 构建**
  - 验收：1440×900、1280×800 下核心五项不打开详情即可读完；390×844 与 200% 缩放保持单列、无横向滚动；`npm --prefix frontend run build` 通过且 `tradingagents/web/static/` 变更与源码同提交。

### G — 评估与切换

- [ ] **T33 架构对照** — 待授权（LLM 批量运行）
  - 验收：同证据集合/cutoff/模型配置的 classic vs catalyst 对照，按设计的 §13.2 固定 provider replay 注入；旧流程 prompt 未被修改以美化结果（diff 证据）；replay 耗时**不**当作 live 性能。
- [ ] **T34 真人阅读验收** — 需用户参与
  - 验收：≥6 个未预读案例、≥3 名目标读者、≥80% 任务 60 秒内正确回答判断/催化/疑点/下一验证；计时与答案表留档；单用户结果单独标注样本限制。
- [ ] **T35 Live smoke 与端到端**
  - 验收：mock 与 live 分开报告；全部回归通过；live 运行的产物路径可复查。
- [ ] **T36 恢复与回滚演练**
  - 验收：中断恢复、profile 不兼容拒绝、投影重建、SSE 断线、并发隔离、开关回滚 6 项各留执行记录；回滚**不清空 run store、不覆盖旧报告**。
- [ ] **T37 文档同步**
  - 验收：README / README.zh-CN / ARCHITECTURE / docs 当前态 / 配置示例 / CHANGELOG 更新；`python scripts/check_agent_docs.py` 通过；**只在功能实际落地后才把新行为写成当前事实**。
- [ ] **T38 验收报告**
  - 验收：按设计的 §16 模板逐字段填写，含已过/失败/未验证/不适用、证据路径、已知限制、最终启用范围。
- [ ] **T39 默认切换**
  - 前提：§6 全部硬门槛通过 **且** 你明确确认。
  - 验收：仅开启 `catalyst_default_web`；**不删除旧 profile、不删除用户数据**；关闭开关后新产物仍可读。

### H — 数据源探测执行

- [ ] **T04 实测**（能力探测）
  - 验收：按 A 的矩阵执行，产出 `docs/superpowers/operations/capability-probe-2026-09-29.md`；每项含能力、adapter 版本、样本范围、探测时间、来源、成功/降级/失败、响应字段摘要、日期/单位验证、限制；**报告不含凭据、不含带 token 的 URL、不含完整私有响应**；无权限的端点标「未验证」而非「可用」。
- [ ] **T16 端点探测**（机构调研）
  - 验收：判定该能力是否合格；不合格则显式延后并写明阻塞原因，不影响 T13–T15 上线。

## 5. 跨 Agent 契约交接

这些是必须由**一方产出、另一方消费**的产物。命名与形状由生产方定义，消费方不自行发明。

| 契约 | 生产方 | 消费方 | 交接方式 |
| --- | --- | --- | --- |
| `catalyst-research-case-v1` schema | C | D、E、F、G | Python canonical model + 序列化 fixture（C 产出，TS 镜像在 B） |
| `catalyst-evidence-policy-v1` 常量与窗口参数 | B | D、E | 独立 policy 文件 + 版本字符串 |
| 探测记录与 provenance | H | A、D | 探测报告文件；D 依赖其结论决定 adapter 范围 |
| 评估表与严重错误定义 | A | G | 冻结的评估表文件 |
| TS wire 联合类型 | B | F | `contracts.ts` 判别联合 |
| fixtures（5 类） | B | C、F、G | 同一份 JSON，双语言可加载 |
| 角色注册与阶段投影 | E | F | `observability/roles.py` 新条目 + 公共阶段投影 |
| static 构建产物 | F | — | `tradingagents/web/static/` 与源码同提交 |

**命名规则**：新角色、产物、policy 全部使用独立名称。禁止把催化角色伪装成旧 `news` 卡片或旧 lens 枚举以绕过 schema（设计的 §5.3）。代码所有的 skill 角色映射只改 `tradingagents/skills/registry.py`，Markdown/preset 无权改变拓扑。

## 6. 全局硬性门槛

任一不通过，**整体不通过**，不允许用其他项的通过来抵消（设计的 §13.3、§15）。G agent 用它做最终判定。

| ID | 门槛 | 谁负责证明 | 通过判据 |
| --- | --- | --- | --- |
| G1 | 首屏唯一 | F | 每个 completed run 仅一份主摘要（DOM 断言 + 截图） |
| G2 | 字符预算 | C + F | 普通简报 ≤420；溢出用 ≤120 模板 + 默认展开完整限制；**限制列表豁免预算但不截断** |
| G3 | 字符计数一致 | C + B | 同一 fixture 前后端计出**同一个数字**（共享样例） |
| G4 | 引用完整 | C | 公开结论/简报引用 100% 可解析；未知不伪装有证据 |
| G5 | 反证处理 | E | 所有 challenge 有 disposition；关键 unresolved 不发布不受限优先级 |
| G6 | 预算与故障 | E | 上限全部生效；失败/超时/取消不制造完整结论、不继续调用 |
| G7 | 同源只读 | C + F | 概要/详情/Markdown 一致；**读取触发的新增 LLM/provider 次数为 0** |
| G8 | 并发与恢复 | E | 跨 run 无串数据；重复/重放幂等；指纹不同拒绝恢复 |
| G9 | 旧功能回归 | E | **基线为 15 failed / 1983 passed**（见 `baseline-pytest-failures.md`）。判定标准是「不得让这 15 项变差、不得新增失败」，**不是**「全绿」——当前基线本身不是全绿 |
| G10 | UI 可用性 | F | 指定屏宽、200% 缩放、键盘导航无阻断 |
| G11 | 严重事实错误 | G | 评估集**零**严重身份错误、未来泄漏、数值/单位错误、无来源确定日期 |
| G12 | 关键风险保留 | G | 人工预标注重大反证/关键缺口 **100%** 保留在简报或常显限制 |
| G13 | 新源可用 | H + D | 宣称启用的 capability 有 live smoke 与 provenance；未验证不算通过 |
| G14 | 配色未漂移 | F | 沿用 `styles/tokens.css` 变量，**未引入草图的独立色板**（diff 证据） |

## 7. 工程检查命令与报告

每个 agent 在自己 worktree 内运行与自身相关的部分，命令取自设计的 §14：

```bash
python scripts/check_agent_docs.py
ruff check tradingagents cli scripts/check_agent_docs.py
npm --prefix frontend run typecheck
npm --prefix frontend run build
python -m pytest
npm --prefix frontend run test -- --run
npm --prefix frontend run test:e2e
git diff --check
git status --short
```

报告规则：区分**本次回归**与**基线既有失败**（用 T01 的清单对照），给出可复现证据。不得修改测试去迎合错误实现；不得把 `skipped` 或 "No checks reported" 当作通过。

每个 agent 的交付报告用设计的 §16 模板的适用子集，外加三段：完成的 T 编号、阻塞点（需改他人负责的文件时写在这里而不自行修改）、未验证项（缺什么、什么条件能补齐）。

## 8. 本轮未执行项

以下按 §1.4 授权与依赖关系未执行，需你另行决定：

| 项 | 原因 |
| --- | --- |
| T33–T35 的 LLM 运行 | 需按实际模型价格核定预算；本轮未授权 |
| T39 默认切换 | 依赖全部前置通过 + 你的明确确认 |
| 任何提交 / 推送 / PR | 未授权；worktree 合回由主会话在你确认后进行 |
| §8.6 完整探测矩阵 | 已完成 raw-vs-qfq 决定性子集，**未覆盖** mootdx、公告、机构调研、分页截断、停牌/新上市、字段缺失、北交所。T13–T16 实施时需自行补测并补全记录 |

## 8.1 探测已确认的缺陷（D 实施时必须处理或显式规避）

以下四项在 2026-09-29 的 live 探测中**已确认**，完整证据见 `docs/superpowers/operations/capability-probe-2026-09-29.md`：

1. **腾讯 kline 列序不是 OHLC** —— 实际 `[date, OPEN, CLOSE, HIGH, LOW, VOL]`。按 OHLC 读会静默得到错误高/低价且不报错。（已并入 T13）
2. **Wind 指数行情代码位错误** —— `get_index_snapshot` 行情侧落到 `000300.OF`（场外基金位）而非 `000300.SH`，返回 0.862–0.966 点（真实沪深300 约 4000）；历史序列四价全等、成交量恒 0.0，**调用成功但数据是错的，比不可用更危险**。`profile`/`fundamentals` 路径用 `000300.SH` 正确，属行情接口代码位问题。修复前**指数行情不得作为市场反应专项的证据来源**。
3. **Wind `TURNOVER` 字段实为成交额（元），不是换手率** —— `volume/100` 与 Tushare `Volume` 比值精确 1.0000；`turnover` 与 Tushare `amount`（千元）隐含比值同为 1.0000。任何按「换手率」解读该字段的代码都是错的，接入时须改名。
4. **mootdx 全线失效且是 registry rank-1** —— 13/13 用例失败：TCP 可连、`Quotes.factory()` 在 3 个服务器上成功，但**每次数据调用返回空 DataFrame 且无列**。它是 `dataflows/registry.py:271` 中 A 股行情链的首位，意味着**每次行情请求先浪费约 26 秒再 fallback**。上游仓库的报告由此独立确认。T13 之前应先把它移出首位或加快速熔断。

**其他已确认事实**：Tushare raw 最可靠（沪深北 40/40 行，标准 OHLC，无重复、无排序错误）；**Tushare qfq 被限流**（`adj_factor` 1 次/分钟，0/2 成功），不能承担多标的串行 qfq；**东财与巨潮在本网络返回 502**（属发布门槛相关）；qfq 链尾的 `yfinance`/`alpha_vantage` 对 A 股复权语义**未验证**，是下一个可能伪装成 qfq 的风险源；北交所是**按源不同**而非整体不支持（Tushare/Wind 完整，腾讯 kline 实际不可用）。
