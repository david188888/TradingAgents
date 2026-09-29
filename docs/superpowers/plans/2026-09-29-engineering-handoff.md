# 催化研究重构：工程交接说明

- **Status: Proposed — 工程交接说明。本文件记录已完成并合回的工作，以及**未完成**的 E/F 产出。不得把 E/F 的产出描述为已完成或已验证。Do not use this document as evidence of current implementation behavior.**
- 创建日期：2026-09-29。交接对象：接手的工程师。
- 上游：[执行计划](2026-09-29-catalyst-research-task-plan.md)（T01–T39 拆分与验收标准）、[设计](../specs/2026-09-28-catalyst-research-redesign.md)、[布局草图](../specs/2026-09-28-catalyst-research-layout.html)。
- `main` HEAD = `3366436`，工作区干净，全部门禁检查通过。**E/F 产出未合回**，按用户指示保留在 worktree。

## 1. 一句话现状

P0–P2 全部完成并合回（7 个 commit，+9119 行代码，2189 测试通过）。**P3（流程 E）与 P4（工作台 F）各有大量产出但未完成、未验证，保留在两个 worktree 分支中。P5（验收 G）未开始，且被四个产品卡点阻塞。**

## 2. 已完成并合回（main 分支，可直接使用）

| 阶段 | 任务 | 交付物 | 测试 |
| --- | --- | --- | --- |
| P0 | T01–T06 | `docs/superpowers/plans/` 下 6 份基线文档 | — |
| P0 | T04 实测、T16 | `docs/superpowers/operations/capability-probe-2026-09-29.md`（439 行 live 探测） | — |
| P0 | 基线 | `docs/superpowers/plans/baseline-pytest-failures.md` | — |
| P1 | T07、T10–T12 | `research/catalyst_evidence_policy.py`、`execution/models.py`、`web/schemas.py`、`web/api.py`、`runtime/fingerprint.py`、`frontend/src/api/contracts.ts`、`shared_fixtures/catalyst/*.json`（6 个 fixture） | 4 个测试文件 + 164 Vitest |
| P1 | T08、T09 | `agents/schemas/_catalyst_research.py`、`web/catalyst_projection.py`、`research/case_assembly.py`、`execution/output_publisher.py` | 94 pytest + 9 Vitest |
| P2 | T-D1、T-D2、T13–T18 | `dataflows/tencent_kline.py`、`dataflows/catalyst_events.py`、`dataflows/registry.py`、`dataflows/mootdx_provider.py`、`dataflows/interface.py`、`dataflows/vendor_errors.py`、`dataflows/stockstats_utils.py` | 51 pytest |

### 2.1 验证状态（`main` @ `3366436`，复现命令）

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate tradingagents
python -m pytest -q -p no:randomly          # 2189 passed / 14 failed
ruff check tradingagents/ tests/              # All checks passed
npm --prefix frontend run typecheck           # clean
npm --prefix frontend run test -- --run       # 32 files / 173 tests
python3 scripts/check_agent_docs.py           # 48 files passed
```

**14 failed 是既有基线，不是回归。** 判定标准是「失败集合不扩大」，不是「全绿」——基线本身就不是全绿。明细见 `baseline-pytest-failures.md`。

### 2.2 顺手修掉的两个现存生产缺陷

- **T-D1 mootdx**：`dataflows/registry.py` 里 mootdx 是 A 股行情链首位，但 live 探测 13/13 失败（TCP 可连、`Quotes.factory()` 成功，数据调用返回无列空 DataFrame），每次请求浪费约 26 秒。已降级到 tushare 之下并加熔断。**其财务/F10 能力保留未删**（设计 §8.2 明确禁止删除）。
- **T-D2 腾讯 kline 列序**：实际是 `[date, OPEN, CLOSE, HIGH, LOW, VOL]`，**不是 OHLC**。按 OHLC 读会静默得到错误的高/低价且不报错。已修正并加不变式 `high >= max(open, close) >= min(open, close) >= low`，该测试已验证在改动前的代码上失败。

### 2.3 关键设计约束（后续修改勿破坏）

- `RuntimePolicyVersion`（`runtime/contracts.py`）是 **horizon 门控专用枚举**，被 5 个文件消费。`catalyst-evidence-policy-v1` **不得**加进这个 Literal——新 policy 走独立模块。
- `web/api.py` 由 B（`research_profile` 校验）与 C（`/catalyst` 路由）共享，合回顺序 B 先 C 后。
- `frontend/src/api/contracts.ts` 是 B 的权威契约。F 期间它保持未改动。字段名不得重新发明（`state`、`verify_first|keep_watching|defer_research|insufficient_information`、`judgement`/`key_evidence`/`next_check`、`counter_evidence|missing_evidence`）。
- 字符预算 fixture `frontend/src/test/fixtures/catalyst-brief-budget.json` 前后端共享，数字固定 **122 / 420 / 83 / 48**，两侧必须一致。

## 3. 未完成：E（流程 P3）— 保留在 worktree

- **分支**：`worktree-agent-ab89cf67e680ed0e9`
- **路径**：`.claude/worktrees/agent-ab89cf67e680ed0e9`
- **基于**：`92a7187`（比 main 少一个 commit `3366436`，即卡点记录文档；代码基线相同）
- **状态**：**未完成**。agent 最后一句是「T23 的负向检查，然后 T24/T25」——即 T24、T25 尚未开始。
- **实测**：`python -m pytest tests/test_catalyst_budget.py tests/test_catalyst_evidence_freeze.py tests/test_catalyst_evidence_steward_split.py tests/test_catalyst_workflow.py -q -p no:randomly` → **107 passed**。但**未跑全量套件**，未验证 classic 回归（T25 是硬门槛），未验证串并行结果一致性。

**未提交文件（8 个）**：

```
tradingagents/execution/budget.py                          预算账本
tradingagents/graph/catalyst_workflow.py                   三专项+反证+综合的 graph
tradingagents/research/evidence_freeze.py                  证据冻结底稿（§5.1，D 范围外的遗留项）
tradingagents/agents/evidence_steward_gating.py           Steward 可复用门控拆分（T23）
tests/test_catalyst_budget.py
tests/test_catalyst_workflow.py
tests/test_catalyst_evidence_freeze.py
tests/test_catalyst_evidence_steward_split.py
```

**剩余工作**：
1. T23 的负向检查（拆分后确认无隐含模型调用绕过 §5.5 预算）
2. **T24**：commit barrier、事件注册、审计、取消、失败与恢复；**重连不重复执行**（SSE 重连后 LLM 调用计数不变）
3. **T25（硬门槛）**：跑全量 pytest 确认失败集合不扩大（须 ≤14 项）；验证 classic 多空辩论、持仓复盘、长期研究路由未被替换；旧角色 key 与 lens 枚举仍服务旧 profile
4. `test_runtime_scaffold.py` 的 3 项前后状态对比（T07/T24 会碰 fingerprint 邻域，这 3 项**本来就是红的**）

**接手命令**：
```bash
cd .claude/worktrees/agent-ab89cf67e680ed0e9
source ~/miniconda3/etc/profile.d/conda.sh && conda activate tradingagents
python -m pytest -q -p no:randomly     # 先拿到全量基线
# 完成后 git checkout 到 main 做 diff 审阅再合回；合回顺序：E 在 C/B 之后
```

## 4. 未完成：F（工作台 P4）— 保留在 worktree

- **分支**：`worktree-agent-a86380eca594832b0`
- **路径**：`.claude/worktrees/agent-a86380eca594832b0`
- **基于**：`92a7187`（同上）
- **状态**：**未完成**。agent 停在「重写 fixtures 为完整 typed wire shapes」中途。
- **实测**：`npm --prefix frontend run test -- --run` → **38 files / 271 tests passed**（基线 32/173，+98）。但 **typecheck 5 处失败**，`npm run build` 状态未知（agent 报告称之前通过，但当前代码已改）。

### 4.1 typecheck 的 5 处失败（必须先修）

```
src/components/layout/WorkbenchLayout.audit.test.tsx(5,34):
  TS6196: 'AuditOpenHandler' is declared but never used
src/components/reader/CatalystProgress.test.tsx(113,38):
  TS2345: Argument of type '"verify_first"' is not assignable to parameter of type 'never'
src/components/reader/CatalystProgress.test.tsx(122,38):
  TS2345: Argument of type '"defer_research"' is not assignable to parameter of type 'never'
src/components/reader/CatalystProgress.test.tsx(127,47):
  TS2345: Argument of type '"insufficient_information"' is not assignable to parameter of type 'never'
src/components/reader/CatalystProgress.test.tsx(132,43):
  TS2345: Argument of type '"insufficient_information"' is not assignable to parameter of type 'never'
```

5 处全在**测试文件**里，不影响运行时。后 4 处同源：`CatalystProgress` 的优先级参数被推断为 `never`，说明该组件的 props 类型尚未接上 `contracts.ts` 的 `verify_first|keep_watching|defer_research|insufficient_information` 联合类型。

### 4.2 未提交文件（26 个）

**新增源码**：`components/reader/CatalystBrief.tsx`、`CatalystCasePage.tsx`、`CatalystProgress.tsx`、`EvidenceDrawer.tsx`、`LegacyReader.tsx`、`components/controls/CatalystForm.tsx`、`components/shared/drawerFocus.ts`、`domain/catalystWorkbench.ts`、`hooks/useCatalyst.ts`、`styles/catalyst.css`

**修改**：`components/layout/WorkbenchLayout.tsx`、`api/client.ts`（仅加 `getCatalyst()`，19 行）、`hooks/useConfig.ts`、`main.tsx`

**新增测试**：`CatalystBrief.test.tsx`、`EvidenceDrawer.test.tsx`、`CatalystProgress.test.tsx`、`WorkbenchLayout.catalyst.test.tsx`、`useConfig.catalyst.test.ts`、`domain/catalystWorkbench.test.ts`

**static 产物（已重建）**：旧 `index-B7hV84WL.js`/`index-o51o60jp.css` 已删，新 `index-DL55Osg4.js`/`index-BpOWPrT6.css` 已生成。**AGENTS.md 要求源码与 static 同提交。**

### 4.3 已完成并验证的部分（可信）

- **T28 七行首屏**、**T29 证据抽屉**：agent 自报完成并有测试。
- **两个同类状态映射 bug**（agent 自查发现）：`complete_limited` 分支因先检查 `partial` 而不可达；级联只从嵌套 `ready` 分支读 completeness/quality 而 `CatalystScreenInput` 提供扁平字段——同一输入两个答案。已修，且把 `LOW_CONFIDENCE`（优先级封顶→第 3 行）与 `partial`（证据缺失→第 4 行）拆开。
- **九状态可达性扫描**：导出 `CATALYST_SCREEN_STATE_IDS` 供测试断言「联合集无成员缺少产生它的输入」，含 3×4×4 共 48 组合网格。
- **安全溢出测试**（`CatalystBrief.test.tsx`，6 个）：四条限制按序渲染、最后一条**全文**存在、无 `<details>`/`aria-expanded`/`hidden`/`aria-hidden`、`role="region"` + `tabIndex=0` + 滚动类（键盘可达）、页脚报 `/ 120 字` 而非 `/ 420 字`、限制字符数（66）超过所报预算数以证明豁免。
- **焦点逻辑**：`Companion`/`Audit` 的机制**逐字提取**到 `shared/drawerFocus.ts`（`restoreFocus` 含 `[inert]` 解包、同一 `FOCUSABLE` 列表、1399px 断点）——是复用不是重写，符合设计 §4.4。
- **`contracts.ts` 未改动**（agent 报 `git diff` 为空）。
- **预算 fixture 未动**，仍 122/420/83/48；计数规则用 `Array.from` 码点复现 Python 侧，四个 case 全部一致。
- **无第二套色板**（G14）：`catalyst.css` 零颜色字面量，连抽屉遮罩也复用 `--shadow-lg`；草图的 `#f5f4ef`/`#245c45` 在 `frontend/src/` 中不存在。

### 4.4 未完成/未验证的部分

- 修完 4 处 typecheck 错误
- 重跑 `npm run typecheck` + `npm run build`，确认 static 产物与源码一致
- **T32 的像素断言尚未做**（需要挂载后可测的页面；CSS 已写并构建过）
- T27 隐藏字段不泄漏的测试（`CatalystForm.tsx` 已建，测试未见）
- 与 E 的真实联调（计划 §2 指出 F 不必等 E，但真实联调应在 E 完成后补）

**接手命令**：
```bash
cd .claude/worktrees/agent-a86380eca594832b0
npm --prefix frontend run typecheck    # 先修那 5 处
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

## 5. P5 验收（G）：四个产品卡点，未决

按用户指示，G 本轮**不做**。以下四项记录在 `2026-09-29-catalyst-research-task-plan.md` §8.0，此处复述供接手者判断。**在 C-1~C-4 决定前，G 只能执行 T36–T38**（T36 恢复/回滚演练、T37 文档同步、T38 验收报告）。

| ID | 阻塞什么 | 需要什么决定 |
| --- | --- | --- |
| **C-1** | **T33 架构对照无法按设计原样执行** | 设计 §13.2 要求「固定共同证据集合、cutoff、模型 ID，通过 provider replay 注入同等资料，classic 的工具查询只命中该集合」。**仓库内无 replay 语料**：T02 的 12 案例中 11 个 `replay_input_ref` 为 `PENDING:BUILD`（`eval-cases.json` 的 `blocking_gaps` 已记录），既有 run 证据在 `~/.tradingagents/` 属用户数据不可提交。**两条路**：(a) 补写 replay 语料并接入 12 案例——新工程量，**不在 T01–T39 内**；(b) 改用 §13.2 第二组「产品端到端对照」，但该组自己写明「不能据此单独声称架构提升准确率」 |
| **C-2** | T33、T35 | 48 次架构对照 + live smoke 的**预算核定**（设计 §14 要求按实际模型价格计算，文档估算不能代替授权） |
| **C-3** | T34、A03 门槛 | 真人阅读验收需**用户或 ≥3 名目标读者**参与，评估 ≥6 个未预读案例、60 秒内答对率 ≥80% |
| **C-4** | T39 | 默认切换需用户最终确认（设计 §11.2 第 3 步 + 项目确认制约定） |

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
- 本轮共 7 次 agent 中途死亡（5 次 HTTP 422「No choices in response」、2 次 stream watchdog 超时），全部是基础设施问题。`SendMessage` 续跑可保留上下文与已产出，建议接手者沿用「实现→测试→运行→下一个，别攒到最后写」的节奏。
- **stash 栈是跨 worktree 共享的**，不要用裸 `git stash pop`。

## 8. 建议的接手顺序

1. 在两个 worktree 里分别修完 E 的 T24/T25 与 F 的 5 处 typecheck，各自跑通本地验证。
2. 合回顺序建议 **F 先、E 后**：F 只依赖已合回的 B/C 契约；E 的 T25 回归要跑全量 pytest，在更完整的主线上做更可靠。
3. E/F 都合回后，重跑 `main` 的全量 pytest 确认失败集合仍 ≤14。
4. 把 C-1~C-4 拿给产品决定。**C-1 不决定，T33 无法执行，整体验收无法判定。**
5. 决定后再派 G 做 T33–T39；在此之前 G 只能做 T36–T38。
