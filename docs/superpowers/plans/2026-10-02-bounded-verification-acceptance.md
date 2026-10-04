# C1 有界条件核查：实施验收

Status: Historical

Do not use this document as evidence of current implementation behavior.

日期：2026-10-02。本批承接[数据整合验收](2026-10-02-research-data-integration-acceptance.md)与已认可的[总体实施计划](2026-09-30-evidence-driven-research-implementation.md)。当前契约以[共享研究记录](../../contracts/research-record.md)和代码为准。

## 交付范围

本批 C1 是三种 record.mode 可调用的有界工具执行器，尚未替换生产研究图：

- canonical `verification-plan-v1` 绑定 run/ticker/mode/date/V0、native hypothesis、单目标 challenge 及已经保存的条件文本，限制一次计划至多三项核查。
- allowlist 工具核查保存的 Tushare 财务数值／同期差值／正基期增长率，或已有量化指标的阈值。源字段须未截断、可用、截止合格；财务披露日期、报告期、单位、来源 family 和非有限值均受检查。未来或缺失数据不生成预测。
- 必要条件为真只支持指定条件，为假则反驳该条件；失效条件为假仍是不确定。所有新记录明确 `predicate_only`，不证明整条假设，不自动关闭关键挑战。文本绑定也不证明数值条件翻译在经济意义上充分。
- 复用已有 run 的 durable ledger/journal，包含此前预算消耗；稳定排序 critical → material → minor。许可持久化前不执行工具，纯本地检查无 HTTP／模型调用。
- 结果及派生血缘保存在 checkpoint，输出重新通过 canonical 校验。V0 与 claims/hypotheses/challenges/metrics 保持；真实核查形成 V1。预算拒绝、取消和不明执行没有伪造的 executed_at；零执行没有 V1。
- 已保存结果可恢复重放；有 dispatch 无结果保持 unknown 并消费原预算，禁止自动重跑。输入或计划改变明确拒绝；输出已保存后，即使存在未解决项，该轮也不重新开启。
- TypeScript mirror 和 Reader 区分条件核查与历史无范围记录；旧字段缺省兼容，生成 static 同步。

派生计算沿用输入来源 family，不能算独立证据来源。指标阈值只核查已保存值，不重新验证原始行情或完整算法。工具不能查询供应商、抽取正文或运行任意代码；兼容记录及手工改标为 native 的 adapted case 均不能进入执行器。

## 验证及审阅边界

离线针对性组合 **158 passed**，其中新增 C1 测试 **96 项**。涵盖三模式、必要／失效条件真伪、比较边界、财务与指标缺失/未来/单位/数值、污染参数与引用、旧 schema/投影、真实 RunStore 的预算拒绝/取消/保存失败/中断恢复/缓存校验。原生产接线测试同时通过，未更改其调用次数与发布门槛。

前端 **43 文件／310 项通过**，`npm ci`、typecheck、build 与 Ruff 通过。自动化验证为 Python／组件测试；没有宣称完成原生浏览器端到端检查。npm 仍有原有 16 项审计告警，构建有主 chunk 超过 500 kB 提示，未扩大到依赖升级。

全量离线命令仍禁用 dotenv，显式排除未标 smoke 的真实 DeepSeek class：

```bash
PYTHON_DOTENV_DISABLED=1 python -m pytest -m 'not smoke' --deselect=tests/test_deepseek_reasoning.py::TestDeepSeekLiveStructuredOutput -q --color=no -p no:randomly --tb=short
```

最终全量：**12 failed／2756 passed／5 deselected／73 subtests passed**。比较基准为整合提交 `8fc9d63` 的既有同环境记录（12 failed／2660 passed）：新增失败集合为空，原失败集合完全相同。保留 graph prefetch 顺序 3 项、fundamentals 日期文本 1 项、runtime v2 描述／指纹／恢复预期 3 项、methodology 字段 2 项、Web CLI 本地日志权限 3 项。**全量 pytest 未全绿**，本批没有放宽或隐藏这些断言。

保留日志：`/tmp/tradingagents-c1-reviewed-offline-20261002.log`。本批没有真实供应商或模型调用，也没有进行付费研究质量评估。最初独立审阅因额度未执行；后续独立审阅发现并复现“取消恢复跳过已缓存结果”的问题。修正为优先保留既有 round 的 completed／unknown，再停止新的 dispatch；补齐单任务及部分完成三任务回归。复审 **Approved for C1**，独立执行 **96 passed**。这些结果不构成研究准确率证据。

另以真实临时 RunStore/journal 生成了明确标记 synthetic 的 JSON 样例：收入 120 对比 100，增长率 0.2；只支持指定必要条件，保存 V0/V1 和派生血缘。预算实际消耗为 round=1、supplement capability=1、data capability=1、HTTP=0、model=0。它不属于真实公司数据或完整研究案例。

## 后续边界

C2 才让三模式专项生成 native hypothesis／结构化条件、挑战选择核查、在最终综合前调用 C1，覆盖请求/恢复/取消/发布和原生只读投影。现有生产路径仍发布空 executed-verification 列表；当前 Reader 原生 publication 尚未接线。完整 D 阅读层次、E 同证据质量／成本对照和默认迁移均未完成。research-only 与 classic 默认保留，不把本批工具执行视为研究准确率提高。
