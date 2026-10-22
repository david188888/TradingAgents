# 整改接力：代码核对与 F02 基线修复

Status: Historical

**Do not use this document as evidence of current implementation behavior.**

日期：2026-10-22。基于 `codex/v8-phase0` / HEAD `e8c283d`，包含已有全部未提交改动。
本次没有替换或清理前序工作。当前契约见[事实前提](../contracts/factual-premises.md)、
[假设导向核查](../contracts/hypothesis-directed-checks.md)及[计量](../contracts/evidence-benchmark.md)。
本记录不是部署或真实模型验收。
同日后续：用户确认并完成 F04 的只读计量/保守清单切片，见
[独立记录](2026-10-22-f04-input-measurement.md)；下文保留此前接力核对时的状态。
2026-10-23 后续：可逆元数据离线 codec 与完整 prompt 对照已完成，见
[实施验收](2026-10-23-f04-metadata-view-validation.md)；当前进度与未关闭项见
[整改待办](../plans/2026-10-21-review-remediation-backlog.md)，本页原建议不再是尚未实施的首个步骤。

## 1. 第一性原理与范围

目标是让研究判断具有可追溯的事实、可解释的核查去向和诚实的失败状态。
核查数量、交付完成、结构校验、经济语义质量分别验收；任何一个都不能替代另外几个。
成本优化必须建立在必要信息保留及可恢复性上，不能通过放宽校验或缩小分母取得。

先对照两份计划及 canonical schema、纯校验、kernel、SDK 适配、恢复、Reader/导出和计量代码，
再复跑限定范围测试。发现计划明确记载两项 F02 问题暂缓，因此先复现并向用户呈现具体修复。
用户本次选择“解除暂缓，先修复这两项”。该授权不包括真实模型、重启、Git 发布或历史数据迁移。

## 2. 实际进度

| 项目 | 本次核对 | 尚未完成 |
| --- | --- | --- |
| F01 | 日历区分自然日、休市见证和已结算交易日；对应离线反例通过 | 没有重新请求真实供应商验证 |
| F06 | 类型化配置/证据/发布错误分别归类；普通 ValueError/KeyError 为内部失败，终态保存一致 | 没有用新真实运行验收 |
| F02 | 观察目录、范围绑定与收据已实现；本次修复最终 Agent 身份遗漏及隔离夹具 | 合法观察旁的无来源自由解释仍可能通过；真实服从度、成本和语义质量未验收 |
| F03 | 字段注册表、11 个独立明细字段、V3 分类、独立命题 V2、一次修复/隔离、任务去向、恢复、回应、Reader/导出和固定分母计量已落地 | 人工确认的重要挑战集、新策略真实模型验证及全量基线仍缺 |
| F04 | 已有综合输入去重与两次全局结构修复上限；回应仍携带允许事实及完整相应来源 | 各任务必需证据清单、确定性视图、修复预留、成本目标和固定证据对照均未完成 |
| F05 | artifact 已按内容寻址；`CatalystJournal.persist()` 仍对累积全状态写入检查点 | 大对象引用格式、旧格式恢复、原子提交/故障注入和完整存储成本对照均未完成 |
| F07 | 已有旧策略样本及评分规则；F03 确定性计数可用 | 新策略固定证据对照、类型化挑战人工匹配、核心结论加权评分与严重错误复核未完成 |
| P3 | `runtime/store.py` 仍导入 `web.batch_models` | 中立模型归属迁移及兼容性回归未实施 |

F03 的 `tests/fixtures/f03-important-challenges-v1.json` 只有两个预标注案例，服务于固定分母反例；
五类与执行失败另外由参数化测试覆盖。二者不能冒充已完成的人工经济质量标注集。
江淮两条旧提议仍仅能拟分类为未来观察，缺观察日期，不能直接满足 V3；不得补造日期或倒填新明细。

## 3. 本次修复

1. **最终 Reader 身份**：`reader_process_projection._context()` 使用 canonical `premise_enabled()`
   核对策略及数值前置条件，将 `factual_premise_policy` 纳入 expected kernel input，只接受 V7。
   保留完整字典相等及输出/记录绑定检查，旧身份缺字段时不升级。
2. **隔离夹具**：保留坏条目的合法事实，再追加 fabricated 引用，令前提门禁通过后到达原引用门禁。
   修改假设数组后重新绑定前提路径；数值 plans/bindings 仍按有效条目的原始索引移动。
   没有把原预期拒绝码改成一个更早的无关错误，也没有放宽生产引用或前提门禁。
3. **身份失败的解释正文**：新增负向断言发现，身份不匹配已返回 unavailable，但仍附带
   `factual_premises` 正文。先复现失败，再将最终前提投影放在身份通过条件内。
   已合格的未发布阶段继续走独立的 stage receipt 校验。
4. **回归缺口**：F03 原管线测试检查了各阶段和正式记录，却没有断言发布后的各 Agent 输出。
   现对有/无 F02 策略的经营、挑战、代码核查、回应及综合逐项断言可读，并检查读取无事件写入。
   单独覆盖未知策略、删除 checkpoint 策略、删除/改写 kernel input 策略及改写 output 策略；
   不匹配时 proposal、stage_record 与前提正文均不暴露。

## 4. 验证口径

所有研究和数据均使用离线合成输入及临时运行目录。未使用真实模型或数据供应商。
测试集合有重叠，不合计为独立用例总数。

| 检查 | 结果 |
| --- | --- |
| 修复前 F03 原分层命令（10-21 记录的 12 文件） | 311 passed |
| 修复前两个 F02 遗留文件 | 3 failed，和历史记录的断言位置一致 |
| 第一轮修复的 F02/F03 四文件回归 | 32 passed；随后增加删除策略反例及解释正文负向断言 |
| 最终 F02/F03 四文件回归（含全部新反例） | 33 passed |
| 最终身份测试单独选择执行 | 6 passed，证明不依赖其它测试先发布 |
| Reader/数值/模型/挑战/benchmark 七文件相邻回归 | 152 passed |
| F01/F06 两文件 | 86 passed |
| 前端全量 Vitest | 58 files / 397 passed |
| typecheck / build | passed，生成 SPA 文件名与本次开始时一致 |
| Reader E2E：F03、F02、结构化财务比较 | 3 passed |
| Ruff / agent docs / diff 检查 | passed；文档检查扫描 165 个 Markdown 文件 |

复现正文泄露的新增断言曾在 `missing_input_policy` 单项中失败；这是本次发现及修复的反例，
不能和原两项 F02 问题的修复前失败混为一谈。
E2E 首次因 macOS 沙箱的 Chromium MachPort 权限失败，三个浏览器用例均未执行；
自动审批允许在沙箱外用同一离线命令重跑后通过。临时 fixture 服务由 Playwright 启停，未重启用户服务。

关键命令（复用既有 Conda `tradingagents`）：

```bash
python -m pytest tests/web/test_specialist_isolation_publication.py \
  tests/web/test_structured_financial_delivery.py tests/test_factual_premises.py \
  tests/test_challenge_pipeline.py -q
python -m pytest tests/web/test_reader_process.py tests/web/test_reader_stage.py \
  tests/test_numeric_pipeline.py tests/test_native_model.py tests/test_challenge_model.py \
  tests/test_challenge_checks.py tests/test_eval_benchmark.py -q
python -m pytest tests/test_native_multisource.py tests/web/test_single_run_manager.py -q
npm --prefix frontend run test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
TRADINGAGENTS_E2E_PYTHON=/Users/david/miniconda3/envs/tradingagents/bin/python \
  npm --prefix frontend run test:e2e -- challenge-checks.spec.ts \
  factual-premises.spec.ts structured-financial-checks.spec.ts
```

未重跑曾访问本地代理的全量 pytest，未修改代理或用户配置；两项已知失败消除不等于证明全量通过。

## 5. 后续推进与待确认决定

建议顺序仍为 F03 验收边界整理 → F04 → F05 → F07 总体验收；P3 可独立处理。
当前 F03 的工程闭环可以进入下一阶段设计，人工标注和真实验收仍保持未完成，不勾掉总体验收项。

F04 建议先做一小步：**只读计量与必需证据清单**。按专项、挑战、回应、综合、修复分解
输入组成及重复项，区分字符/字节估计、已保存 SDK tokens 和未知用量；不把字符下降等同于真实 tokens 下降。
用冻结离线输入枚举 F02 observations、数值 anchors/receipts、合法引用、期次/口径、来源限制与冲突/反证，
为后续视图比较建立明确的保留要求。旧策略保存运行只作旧基线，不能冒充 F02/F03 新策略成本。

后续才决定以下政策，不能在计量阶段顺带实施：

- 视图选择：先保留全部必要证据再去重，或按任务选择；必须说明任何删减的经济信息边界。
- 修复预留：在现有总尝试上限内预留综合修复，意味着早期专项可用修复机会减少；
  必须确定预留、借用、并发及恢复规则，不能只声称“预留一次”却忽略全局 attempts。
- 成本目标：先冻结度量与对照，再约定目标，真实模型/样本/预算另行确认。

F05 还需确认新对象格式及启用范围、恢复兼容和可接受读写成本。F07 继续沿用已确认评分者，
不得默认由本次 Codex 会话替代 Claude 的人工分数。真实模型运行数和预算尚未获批。
