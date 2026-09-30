# 催化研究重构：工程交接说明

- **Status: Updated 2026-09-30 — P3（E）与 P4（F）已全部完成、验证并合回 `main`，两棵 worktree 与分支已删除。当前 `main` HEAD = `1856391`（全部本地提交，未推送）。接线（§3.4）已出方案但未获批、未动代码。剩余阻塞在 §5 的四个产品卡点，其中 C-1 gate 住 T33 与整体验收判定。**
- 创建日期：2026-09-29，最近更新：2026-09-30。交接对象：接手的工程师。
- 上游：[执行计划](2026-09-29-catalyst-research-task-plan.md)（T01–T39 拆分与验收标准）、[设计](../specs/2026-09-28-catalyst-research-redesign.md)、[布局草图](../specs/2026-09-28-catalyst-research-layout.html)。
- **本文档已按 2026-09-30 的实测重写 §1–§5。§6（探测遗留）与 §7（环境注意事项）仍然有效，原文保留；§8 已按新现状重写。**
- 原始记录（2026-09-29 21:5x 复核）见 §9，其中的归因更正依然成立，追加更正见 §9.1。

## 1. 一句话现状

**P0–P4 全部完成并合回 `main`。P5（验收 G）未开始，被四个产品卡点阻塞，其中 C-1 gate 住 T33 与整体验收判定。**

合回顺序为 F 先、E 后（约束见 §2.3 `web/api.py`）。两条 worktree 分支的产出已全部并入 main，可删除。

## 2. 已完成并合回（main 分支，可直接使用）

| 阶段 | 任务 | 交付物 | 测试 |
| --- | --- | --- | --- |
| P0 | T01–T06 | `docs/superpowers/plans/` 下 6 份基线文档 | — |
| P0 | T04 实测、T16 | `docs/superpowers/operations/capability-probe-2026-09-29.md`（439 行 live 探测） | — |
| P0 | 基线 | `docs/superpowers/plans/baseline-pytest-failures.md` | — |
| P1 | T07、T10–T12 | `research/catalyst_evidence_policy.py`、`execution/models.py`、`web/schemas.py`、`web/api.py`、`runtime/fingerprint.py`、`frontend/src/api/contracts.ts`、`shared_fixtures/catalyst/*.json`（6 个 fixture） | 4 个测试文件 + 164 Vitest |
| P1 | T08、T09 | `agents/schemas/_catalyst_research.py`、`web/catalyst_projection.py`、`research/case_assembly.py`、`execution/output_publisher.py` | 94 pytest + 9 Vitest |
| P2 | T-D1、T-D2、T13–T18 | `dataflows/tencent_kline.py`、`dataflows/catalyst_events.py`、`dataflows/registry.py`、`dataflows/mootdx_provider.py`、`dataflows/interface.py`、`dataflows/vendor_errors.py`、`dataflows/stockstats_utils.py` | 51 pytest |
| **P4** | **T26–T32** | **工作台页面**：`components/reader/CatalystBrief.tsx`、`CatalystCasePage.tsx`、`CatalystProgress.tsx`、`EvidenceDrawer.tsx`、`LegacyReader.tsx`、`components/shared/drawerFocus.ts`、`domain/catalystWorkbench.ts`、`hooks/useCatalyst.ts`、`styles/catalyst.css`；改动 `WorkbenchLayout.tsx`、`api/client.ts`、`hooks/useConfig.ts`、`main.tsx` | **41 files / 297 Vitest** |
| **P3** | **T19–T25** | **流程引擎**：`execution/budget.py`、`graph/catalyst_workflow.py`、`research/evidence_freeze.py`、`agents/evidence_steward_gating.py` | **131 pytest** |

### 2.1 验证状态（`main` @ `af90488`，2026-09-30 实测）

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate tradingagents
python scripts/check_agent_docs.py                                    # 49 files passed
ruff check tradingagents cli scripts/check_agent_docs.py             # All checks passed
npm --prefix frontend run typecheck                                  # clean
npm --prefix frontend run test -- --run                              # 41 files / 297 tests
python -m pytest tests/test_catalyst_workflow.py \
  tests/test_catalyst_budget.py tests/test_catalyst_classic_regression.py \
  tests/test_catalyst_evidence_freeze.py tests/test_catalyst_evidence_steward_split.py \
  -q -p no:randomly --color=no                                       # 131 passed
python -m pytest -q -p no:randomly --color=no                        # 13 failed / 2321 passed
```

**13 failed 是既有基线，不是回归。** 判定标准是「失败集合不扩大」，不是「全绿」——基线本身就不是全绿。明细见 `baseline-pytest-failures.md`。

第 13 项是 `test_wind_provider.py::TestConfigFlag::test_explicitly_disabled_returns_data_unavailable`，即基线文档开篇第 5 行已记录的**偶发失败**项：单独运行 1 passed（8.94s），该文件不 import 任何 catalyst 代码。基线 12 项与本次实测**逐条同名同类，0 项消失**。

> `pytest` 必须加 `--color=no` 才有可解析的 `FAILED` 行。默认彩色输出会让 `grep '^FAILED'` 抓不到任何内容，导致失败集合比对静默变成「0 项，集合未扩大」。**本轮实际踩到过一次**：比对时因一条测试名笔误（漏写 `_first_`）产生了假的差异项，修正后才是真实的 13 vs 12。比对前先确认两侧名单本身没有打字错误。

### 2.2 顺手修掉的三个现存生产缺陷

- **T-D1 mootdx**：`dataflows/registry.py` 里 mootdx 是 A 股行情链首位，但 live 探测 13/13 失败（TCP 可连、`Quotes.factory()` 成功，数据调用返回无列空 DataFrame），每次请求浪费约 26 秒。已降级到 tushare 之下并加熔断。**其财务/F10 能力保留未删**（设计 §8.2 明确禁止删除）。
- **T-D2 腾讯 kline 列序**：实际是 `[date, OPEN, CLOSE, HIGH, LOW, VOL]`，**不是 OHLC**。按 OHLC 读会静默得到错误的高/低价且不报错。已修正并加不变式 `high >= max(open, close) >= min(open, close) >= low`，该测试已验证在改动前的代码上失败。
- **串并行预算竞态（P3 合回前修复）**：见 §3.1。

### 2.3 关键设计约束（后续修改勿破坏）

- `RuntimePolicyVersion`（`runtime/contracts.py`）是 **horizon 门控专用枚举**，被 5 个文件消费。`catalyst-evidence-policy-v1` **不得**加进这个 Literal——新 policy 走独立模块。
- `web/api.py` 由 B（`research_profile` 校验）与 C（`/catalyst` 路由）共享，合回顺序 B 先 C 后。
- `frontend/src/api/contracts.ts` 是权威契约。**F 期间与 E 期间均保持零改动**（已实测 `git diff` 为空）。字段名不得重新发明（`state`、`verify_first|keep_watching|defer_research|insufficient_information`、`judgement`/`key_evidence`/`next_check`、`counter_evidence|missing_evidence`）。
- 字符预算 fixture `frontend/src/test/fixtures/catalyst-brief-budget.json` 前后端共享，数字固定 **122 / 420 / 83 / 48**，两侧必须一致。

## 3. 已完成：E（流程 P3）

- **commit**：`4c4756d`（feat）→ `af90488`（merge 到 main）
- **交付物**：`execution/budget.py`（767 行预算账本）、`graph/catalyst_workflow.py`（1724 行流程引擎）、`research/evidence_freeze.py`（991 行证据冻结）、`agents/evidence_steward_gating.py`（307 行 Steward 门控拆分）
- **测试**：5 个文件共 **131 passed**（125 原有 + 6 为竞态修复新增）

### 3.1 合回前修复的串并行预算竞态

**这是真实缺陷，不是测试覆盖不足。** T20 要求「串行降级不改变结论语义」，但当专项预算不足时，**哪个角色被拒绝是结论的一部分**。

`BudgetLedger` 线程安全，从不超支；但修复前每个角色在自己的工作线程里各自 `ledger.reserve()`，于是**谁抢到最后一个额度由调度器决定**。实测（上限 2、并发 2、三角色争抢）：

```
串行   ×5 ：5/5 得到 (catalyst_events, operating_delivery)   ← 严格按 ROLE_ORDER
并行   ×8 ：7/8 得到 (catalyst_events, market_reaction)      ← 调度器决定
```

**修法**：把 `ledger.reserve()` 提前到主线程，在 `pool.submit` 之前按 `ROLE_ORDER` 同步跑完一轮；模型调用仍在 `ThreadPoolExecutor` 内并发。两个推论都必须处理，缺一即串并行不等价：

1. **预留循环必须跳过能力阻塞角色**——否则为注定 SKIPPED 的角色白占额度，下一角色会拿到串行路径不会产生的拒绝。
2. **cancel 后必须 `ledger.release()` 回收**——取消的 run 不能白占额度影响后续 run。

实现上 `run_specialist` 新增一个带哨兵默认值的 `reservation` 参数（区分「未提供」/「已授权」/「已拒绝」三种状态），因此**所有既有直接调用方行为不变**。

**修复后实测**（上限 1/2/3 三档，并行各 ×20）：存活角色恰好是 `ROLE_ORDER` 的前缀，与串行 **100% 一致**；上限 2 时并行 20/20 均为 `(catalyst_events, operating_delivery)`。

**测试有效性已反向验证**：把预留循环临时改回修复前行为，新测试立即失败并复现出**原始症状** `(catalyst_events, market_reaction)`，恢复后全绿。5 个新测试连跑 3 次稳定。其中 `test_a_ample_budget_leaves_the_parallel_path_actually_concurrent` 是刻意加的——修复只应序列化**预留**，不该序列化模型调用；没有它，一个「在主线程跑完整段调用」的错修法能通过所有等价性测试而悄悄把 SS5.4 并发上限降成 1。

### 3.2 已知的串并行不对称（留档，本次不修）

串行分支每跑完一个角色会 `if cancel(): break`，并行分支三个角色已全部 submit 不会提前退出，因此 **cancel 场景下 `slots` 长度本身就不同**（串行 1 条 / 并行 3 条 CANCELLED）。

它**没有进入公共产物**——取消的 run 什么都不发布，所以「公共产物逐字相同」在这种情况下平凡成立。因而不扩大范围去动它，但接手方若修改 `execute_specialists` 的取消路径，须知道这个不对称存在。

### 3.3 T25 的行为断言已补齐

原文档称 T25 的「行为断言」待补。实际 `tests/test_catalyst_classic_regression.py` 已有 **9 条**针对性断言，覆盖：classic 多空辩论节点仍接线、classic graph setup 不 import catalyst workflow、executor 未引用 catalyst workflow、`research_mode` 仍提供持仓复盘、`research_profile` 仍恰为 classic 与 catalyst_v1 两项、long horizon 值仍在请求上、case assembly 仍受两个 learning mode 门控、classic 角色 registry key 未变、horizon lens 枚举未变。

T25 两半均已完成：失败集合未扩大（§2.1）+ 行为断言（上述 9 条）。

### 3.4 未接线项（有意保留，非缺陷）

- **`run_catalyst_research` 零生产调用方**。已实测 `grep -rn "run_catalyst_research" tradingagents cli`，除定义外无任何命中；2026-09-30 复测全仓库（含 `tests/`）亦仅命中测试文件。流程引擎目前只能经测试调用。这是**「真实接线」的未来工作**，但它意味着 P3 的产物目前没有任何用户可达路径。
- **`research_profile` 被校验但不被执行路径消费（2026-09-30 接线调查实测）**。这是上条更刺眼的一面：
  - `grep -rn "research_profile" tradingagents` 在 `web/` 之外的命中只有三处——`execution/models.py`（请求字段 `ResearchProfile = "classic"` 及其 policy version 投影）、`research/catalyst_evidence_policy.py`（`normalize_research_profile` 归一化）、`agents/schemas/_catalyst_research.py`（`Literal["catalyst_v1"]` 的响应侧字段）。
  - `manager.py`、`broker.py`、`scheduler.py` 与 graph 执行路径**零命中**。
  - **后果**：`web/api.py:_normalize_research_profile` 会接受并校验 `catalyst_v1`，但请求随后**被当作 classic 跑掉**，没有任何执行分叉。当前不存在 catalyst 执行分支——不是「接线不完整」，是「入口承认了它、下游不认识它」。
  - `EvidenceFreezer`（`research/evidence_freeze.py:801`）是 `FrozenEvidenceDraft` 的唯一生产构造点，接线时从它取草稿。
- **T24 采用窄范围**：只补模块层语义与测试（commit barrier、事件注册、审计、取消、失败与恢复、重连不重复执行），不做 HTTP/SSE 层的真实接线。理由与上条相同：接线会触及 `web/api.py`，而该文件由 B/C 共享，属另一次有独立风险的改动。
- **接线的四步方案已出，未获批、未动代码**（2026-09-30 收尾时用户指示「先停下来，存入记忆与文档」）：(1) 在 `manager.py` 按 `request.research_profile` 分流，`catalyst_v1` 走 `EvidenceFreezer` → `run_catalyst_research`，classic 保持原路径，**不改 `RuntimePolicyVersion`**；(2) 把 `CatalystForm.tsx` 接进工作台并重建 `web/static/`；(3) 接线时须处理 §3.2 的取消路径 `slots` 长度不对称；(4) 接线后 T32 浏览器验证才可执行（需本地 LLM 配置）。

## 4. 已完成：F（工作台 P4）

- **commit**：`2136cc1`（feat）→ `3cee419`（merge 到 main）
- **验证**：typecheck clean；**41 files / 297 Vitest passed**；`npm run build` 复现出**逐字节相同**的产物哈希（`index-BQAQBYRZ.js` / `index-BpOWPrT6.css`），合回后工作树保持干净；`tradingagents/web/static/` 已同步提交。

### 4.1 原 typecheck 5 处错误的成因与修法（已实施）

原 5 处全在**测试文件**里，不影响运行时产物。真实成因不在组件 props——`CatalystProgress.tsx` 的 props 正常 import 自 `domain/catalystWorkbench`，`contracts.ts` 零改动且 `CatalystReadyV1DTO.priority` 定义正确。

真因是测试辅助函数 `CatalystProgress.test.tsx:60` 把条件类型写在**裸类型参数**上：

```ts
priority: CatalystReadState extends { priority?: infer P } ? P : never,
```

`CatalystReadState` 是**三成员联合**（`contracts.ts:1980`），`priority` 只存在于 `CatalystReadyV1DTO`。条件类型写在裸类型参数上时不做分配，对具体联合类型整体不 `extends` 该对象形状，于是落入 `: never` 分支。

修法：改用 `contracts.ts:1741` 已导出的 `CatalystResearchPriority`。**未使用** `as never` / `as any` / `@ts-expect-error`——该文件顶部注释明确说明「a partial literal would typecheck under `as never` and would stop being a statement about the wire at all」。第 1 处 `TS6196` 是 `WorkbenchLayout.audit.test.tsx:5` 的未使用具名导入，删掉即可。

修复过程中还清除了 `ready()` 辅助函数里残留的 3 处 `as` 收窄断言，改为经导出的 `CatalystCompleteness` / `CatalystResearchQuality` 构造完整 wire fixture。

### 4.2 static 产物曾落后于源码（已重建）

原产物时间戳 17:49，而 **12 个 `frontend/src/` 文件比它更新**（含运行时源码而非仅测试）。`index.html` 的引用与磁盘文件自洽，但那只是 17:49 那次 build 的产物，不代表当前源码。已重建并随源码同提交。

### 4.3 可信产出（已验证）

- **T28 七行首屏**、**T29 证据抽屉**。
- **两个同类状态映射 bug**（F 自查发现并修复）：`complete_limited` 分支因先检查 `partial` 而不可达；级联只从嵌套 `ready` 分支读 completeness/quality 而 `CatalystScreenInput` 提供扁平字段——同一输入两个答案。已修，且把 `LOW_CONFIDENCE`（优先级封顶）与 `partial`（证据缺失）拆开。
- **九状态可达性扫描**：导出 `CATALYST_SCREEN_STATE_IDS`，含 3×4×4 共 48 组合网格断言「联合集无成员缺少产生它的输入」。
- **安全溢出测试**（6 个）：四条限制按序渲染、最后一条**全文**存在、无 `<details>`/`aria-expanded`/`hidden`/`aria-hidden`、`role="region"` + `tabIndex=0` + 滚动类（键盘可达）、页脚报 `/ 120 字` 而非 `/ 420 字`、限制字符数（66）超过所报预算数以证明豁免。
- **焦点逻辑**：`Companion`/`Audit` 的机制**逐字提取**到 `shared/drawerFocus.ts`——是复用不是重写，符合设计 §4.4。
- **预算 fixture 未动**，仍 122/420/83/48；计数规则用 `Array.from` 码点复现 Python 侧，四个 case 全部一致。
- **无第二套色板**（G14）：`catalyst.css` 零颜色字面量；草图的 `#f5f4ef`/`#245c45` 在 `frontend/src/` 中不存在。

### 4.4 仍未完成的两项

- **T32 只做了 jsdom 结构性断言，未做浏览器验证**。八态矩阵、配色未漂移（G14）、字符预算前后端一致这三项都经过了 jsdom 层断言，但**没有在真实浏览器里打开过页面**。这是 T32 剩余的唯一缺口。
- **`CatalystForm.tsx` 未接线**。已实测：它**只被自己的测试文件引用**，`frontend/src/` 下无任何生产代码 import 它。页面因此**没有创建 catalyst_v1 run 的入口**。按窄范围决策保留未动——接线会新增 `web/api.py` 调用方，属独立风险。T27「隐藏字段不泄漏」的测试已随该组件存在（`CatalystForm.test.tsx`）。

## 5. P5 验收（G）：四个产品卡点，未决

按用户指示，G 尚未开始。以下四项记录在 `2026-09-29-catalyst-research-task-plan.md` §8.0，此处复述供产品决定。**在 C-1~C-4 决定前，G 只能执行 T36–T38**（T36 恢复/回滚演练、T37 文档同步、T38 验收报告）。

| ID | 阻塞什么 | 需要什么决定 |
| --- | --- | --- |
| **C-1** | **T33 架构对照无法按设计原样执行** | 设计 §13.2 要求「固定共同证据集合、cutoff、模型 ID，通过 provider replay 注入同等资料，classic 的工具查询只命中该集合」。**仓库内无 replay 语料**：T02 的 12 案例中 11 个 `replay_input_ref` 为 `PENDING:BUILD`（`eval-cases.json` 的 `blocking_gaps` 已记录），既有 run 证据在 `~/.tradingagents/` 属用户数据不可提交。**两条路**：(a) 补写 replay 语料并接入 12 案例——新工程量，**不在 T01–T39 内**；(b) 改用 §13.2 第二组「产品端到端对照」，但该组自己写明「不能据此单独声称架构提升准确率」 |
| **C-2** | T33、T35 | 48 次架构对照 + live smoke 的**预算核定**（设计 §14 要求按实际模型价格计算，文档估算不能代替授权） |
| **C-3** | T34、A03 门槛 | 真人阅读验收需**用户或 ≥3 名目标读者**参与，评估 ≥6 个未预读案例、60 秒内答对率 ≥80% |
| **C-4** | T39 | 默认切换需用户最终确认（设计 §11.2 第 3 步 + 项目确认制约定） |

**C-1 不决定，T33 无法执行，整体验收无法判定。**

另需产品注意：按 §3.4 与 §4.4，`run_catalyst_research` 目前零生产调用方、`CatalystForm` 未接线，因此**即使 C-1~C-4 全部决定，端到端用户路径仍需先接线**才能做真实的端到端验收。

## 6. 探测遗留的未验证项（写 T38 时须带上）

来自 `capability-probe-2026-09-29.md` 与 D 的报告：

- **T16 机构调研**：模块与门控已实现（管理层表述不升级为订单事实），但**端点未实测**，「显式延后」分支未经测试。H 判定：可达源中无可探测端点，互动易是机构调研的反面。
- **Wind vs 腾讯 qfq 不可互换断言**：未完成——需实时复权因子快照，探测时取不到。已实测二者比值逐日变化（0.99556→0.99503），anchor 一致但复权因子算法不同。
- **PIT 资格**：Wind 与腾讯同属「qfq to today」anchor，最新 bar 天然等于 raw，**故最新窗口内 raw 与 qfq 不可区分——这不等于 qfq 正确**。跨公司行动稳定性未测。历史 cutoff 的 qfq 在补齐因子快照前**不得进入市场专项上下文**。
- **Wind 指数行情代码位错误**：`get_index_snapshot` 落到 `000300.OF`（场外基金位）返回 0.862–0.966 点（真沪深300 约 4000），四价全等、成交量恒 0。`profile`/`fundamentals` 路径用 `000300.SH` 正确。修复前指数行情不得作为市场反应专项证据。
- **Wind `TURNOVER` 实为成交额（元）**，非换手率；`volume/100` 与 Tushare `Volume` 比值精确 1.0000。按「换手率」解读该字段的代码是错的。
- **T17 的 ≤3 能力补充预算**：属预算管道，不在 `dataflows/`，D 未做，E 是否补做待确认。
- **完整 §8.6 探测矩阵未覆盖**：mootdx、公告、机构调研、分页截断、停牌/新上市、字段缺失、北交所。T13–T16 实施时需自行补测。

## 7. 环境注意事项（接手前必读）

- **用 conda 环境 `tradingagents`**（`source ~/miniconda3/etc/profile.d/conda.sh && conda activate tradingagents`），仓库内无 `.venv`。若 worktree 中 `source` 被拒，直接调 `~/miniconda3/envs/tradingagents/bin/python`。
- **`Agent(isolation: "worktree")` 总是从 `origin/main` 新建 worktree**，不包含本地未推送提交。若要带 spec 文档，用绝对路径引用主 checkout 的 `docs/superpowers/`，或手动 `git worktree add` 到目标 commit。
- **worktree 不共享 `node_modules`**：每个前端 worktree 需 `npm --prefix frontend ci`。
- **stash 栈是跨 worktree 共享的**，**绝不要用裸 `git stash pop`**。若必须 stash，用 `git stash push -u -m "<唯一标签>"`，立即用 `git stash list --format='%H %gs'` 记下 SHA，用 `git stash apply <sha>` 恢复（不是 pop），事后按标签重新定位 `stash@{n}` 再 drop。
- **zsh 会吞掉未加引号的 `--include=*.py` / `--include=*.tsx`**（报 `no matches found`），导致 `grep` 静默返回空，误判为「无引用」。核实「某符号是否真的没有调用方」时**必须确认 grep 本身没有报错**——本轮就差点把一次失败的 grep 当成证据。
- **`pytest` 判定失败集合必须带 `--color=no`**（见 §2.1）。
- **subagent 派发可能被 auto mode 拦截**：2026-09-30 实测 `SendMessage` 与 `Agent` 均返回「分类器无裁决结果，重试无效」。若再次发生，只读操作不受影响，可先自行核实事实，再决定是否由主 agent 实施。

## 8. 建议的接手顺序

0. **已完成、无需重复**：E 的全量 pytest 与失败集合比对、串并行竞态的复现与修复、F 的 typecheck 修复与 static 重建、E/F worktree 与分支的删除、E 交付物清单的逐项核对（E 自报的 11 项中 `test_catalyst_events_t14_t18.py` 与 `test_catalyst_fixtures.py` 实为 `92a7187` 的既有文件，**main 上无缺失**）。接手方从第 1 步开始。
1. **补 T32 的浏览器验证**：启动 `tradingagents web --port 8765 --open`，实际打开工作台页面，验证八态矩阵渲染、G14 配色未漂移、字符预算 fixture 前后端一致。需本地可用的 LLM 配置才能跑真 run。
2. **把 C-1~C-4 拿给产品决定**。**C-1 不决定，T33 无法执行，整体验收无法判定。**
3. 决定后再派 G 做 T33–T39；在此之前 G 只能做 T36–T38。
4. **接线**（`run_catalyst_research` 的生产调用方 + `CatalystForm` 入口）是端到端验收的前置条件，见 §3.4 与 §5 末段。**方案已出（§3.4 末条），但 2026-09-30 用户明确指示「先停下来，存入记忆与文档」，故未获批、未动代码。**

> **注意**：仓库内尚有 **7 棵历史遗留 worktree**（5 棵 `a6a3f4c` 的 `worktree-agent-*`、1 棵 detached `ca90f27`、1 棵 codex 的 `upstream-sync-20260925`），均与本轮 catalyst 收尾无关，**已报告用户，未触碰**。清理前须逐个确认无未提交产出。

## 9. 历史复核记录（2026-09-29 21:5x）

对上一版交接说明做的独立复核，全部为重新执行、非引用自报。

| 项 | 上一版说法 | 复核实测 | 处理 |
| --- | --- | --- | --- |
| E 全量回归 | 「未跑全量套件，未验证 classic 回归」 | 14 failed / 2296 passed，14 条与基线**逐条同名**，无新增 | 补记；T25 拆为「失败集合已证 / 行为断言待补」 |
| F typecheck 成因 | 「组件 props 尚未接上 `contracts.ts` 联合类型」 | props 与 `contracts.ts` 均正常；真因是测试第 60 行条件类型写在裸类型参数上 → `never` | §4.1 整段重写并给出行号与修法 |
| F static 产物 | 「已重建」，列入可信产出 | 产物时间戳 17:49，**12 个源码文件更新于其后**（含运行时源码） | 标为过期，改为「必须重建」 |

以上三项均已在 2026-09-30 处理完毕（§3、§4.1、§4.2）。

### 9.1 2026-09-30 追加的更正

原文档对 E 剩余工作量的估计**偏高**，来源是三处与实测不符的描述：

- **「串并行结果一致性未验证、没有对应断言测试」——不成立**。`test_serial_and_parallel_runs_produce_identical_public_cases` 当时已存在，且已钉住 `f.{role}.i0` 的合并顺序。真正的缺口不是「没有测试」，而是**该测试只在预算充足时成立**——预算一紧，并行与串行产出不同，而没有任何测试覆盖那种情形。修复见 §3.1。
- **「T24 的 resume/barrier 测试不存在」——不成立**，相关测试当时已存在。
- **「T23 只有部分测试」——不成立**，当时已有 15 条。

此外：

- **基线文档曾把两个 ollama 测试归入「Wind 合约漂移」类**——分类错误，已在 `90a45d3` 更正（它们测的是 `cli/utils.py` 的 ollama endpoint 提示，与 Wind 无关），并记录 2026-09-30 复测已转绿。
- **两个 ollama 测试的转绿根因未定位**。`cli/utils.py` 与 `tests/test_ollama_base_url.py` 自 `ca90f27` 起零改动，单独运行 15 passed，因此最可能是全量套件中其它模块改变了导入或控制台状态所致的跨测试干扰。此处只记录实测事实，**不作因果断言**。
