# F03 独立核查命题：实施与离线验收

Status: Historical

**Do not use this document as evidence of current implementation behavior.**

日期：2026-10-21。范围：当前工作区，在保留前序全部未提交改动的基础上实施用户确认的
[F03 第 10 节方案 A](../plans/2026-10-21-f03-hypothesis-directed-checks.md#10-a挑战独立核查命题的实施设计)。
当前契约见[假设导向核查](../contracts/hypothesis-directed-checks.md)。本记录不代表部署或真实模型验收。

## 1. 实施范围

- 新建 V7 冻结 `hypothesis-directed-checks-v1`，选择挑战 V3 与 `verification-plan-v2`。
  历史无该身份时仍使用旧挑战和原条件任务；新增字段省略，旧序列化摘要回归保持不变。
- material / critical 必须分类。代码核对五种分类、类型化所需输入、未来日期、字段/工具能力、
  增长基数适用域以及事实/来源作用域。自然语言资料需求保留为模型提出、可用性未知。
- 独立核查命题绑定挑战与冻结证据，不改写原假设条件。新增事实只支持该挑战及其定向回应；
  操作数、门槛、日期继续经过数值与 F02 收据。财务两期比较禁止跨 evidence ID 拼接。
- 现有一次修复受共享总预算约束；修复整体有效时替换原提议，否则保留有效主提议条目、原始索引和收据。
  被拒正文不进入正式产物；全部拒绝与合法零挑战区分。
- 保存未生成、已执行、预算拒绝、取消与未知派发等去向。工具异常属于已执行但未得到谓词结果。
  保存结果优先于后续取消；未知派发不重试；恢复不重复请求。
- Reader、相关依据、阶段产物和 Markdown 展示分类、输入需求、命题、任务去向和结果作用域。
  保存结果由纯函数复核；读取不派发核查、不取数、不调用模型、不写运行。
- benchmark 分离已接纳完整率、固定样本覆盖率、正确任务生成率、实际执行率与成功结果率。
  保留首次拒绝及修复删除数量；未知人工标注不记零、不推导覆盖率。回应变化不等于判断质量改善。

## 2. 验证

使用既有 Conda `tradingagents`，无真实模型/数据供应商请求；浏览器使用隔离的合成 fixture。

| 检查 | 结果 |
| --- | --- |
| F03 三个专项文件（分类/执行、SDK 隔离、保存阶段/发布整链路） | 最终专项 41 passed |
| 后端分层回归，含旧有界核查、字段、模型、请求、数值、benchmark 与阶段 Reader | 310 passed |
| 分层回归后新增未来期次反例，F03 三文件与 benchmark 最终复测 | 50 passed |
| 前端完整 Vitest | 58 files / 397 passed |
| Reader E2E：F03、F02 前提展示、结构化财务比较 | 3 passed |
| Ruff：`tradingagents cli`、相关脚本和新增测试 | passed |
| `check_agent_docs.py`、`git diff --check` | passed |
| `npm ci`、typecheck、build，含生成 SPA | passed |

后端分层命令（当轮包含 40 项 F03 测试；随后新增一项“缺来源不能隐藏未来财务期次”负向用例，
最终 41 项 F03 与 9 项 benchmark 复测通过。这些数量重叠，不相加）：

```bash
python -m pytest tests/test_challenge_checks.py tests/test_challenge_model.py \
  tests/test_challenge_pipeline.py tests/test_bounded_verification.py \
  tests/test_financial_detail_fields.py tests/test_native_model.py \
  tests/test_native_research.py tests/test_native_request.py \
  tests/test_numeric_narrative.py tests/test_numeric_pipeline.py \
  tests/test_eval_benchmark.py tests/web/test_reader_stage.py -q
```

E2E 使用真实本地 HTTP/SSE、运行保存与 Reader 投影，数据和模型均为合成。
覆盖可算、资料可用性未知、未来观察、相关依据和 390px 无横向溢出，人工检查了保存截图。
首次浏览器启动因 macOS 沙箱权限被阻止；经授权以同一离线命令在沙箱外重试。
首次进入页面时，夹具缺少数值锚点要求的完整事实绑定，生产门禁正确拒绝；仅修正夹具，未放宽校验。

## 3. 固定分母与失败反例

固定合成标签在 [`f03-important-challenges-v1.json`](../../tests/fixtures/f03-important-challenges-v1.json)
中预先保存，测试在执行前加载；其标签由开发会话按确定性合成输入构造，不是 F07 人工经济质量评分。

- 固定标注两项重要挑战，实际只接纳一项时：已接纳完整率可以为 1，但固定样本覆盖率为 1/2。
- 正确绑定任务为 1/1；换错门槛的期望任务不计入成功分子。
- 同一目标重复生成两项任务不能让一个标注案例的覆盖分子超过 1。
- 工具失败：实际执行率 1/1、成功结果率 0/1；预算拒绝：实际执行率 0/1，没有执行时间。
- 中断后未知派发保持 unknown；结果已保存后再取消保留 completed，不重复执行。
- 没有预标注的真实运行，其分类覆盖率与正确任务生成率为 null。

## 4. 江淮两条真实挑战的离线重标注

[冻结标注 JSON](2026-10-21-f03-offline-challenges.json)从原正式记录只读提取，校验文件 SHA-256：
`0ab221ec7c4ed0f0481d690345aa0cfbc9556534bd5a35edbeea3b1fd56e489c`。
JSON 保存 V0 摘要、来源内容哈希、原挑战/目标 ID 和标注理由。

两条原提议都要求后续披露，拟分类均为 `future_observation`，但原记录都未保存明确观察日期。
因此 **0/2 能直接满足 V3 日期要求**；没有替旧模型选择日期，也没有把它们改标成当前可算。
它们仍是旧策略记录，Reader 的历史分类保持未知，不以人工重标注冒充新模型输出。
旧证据不含后续扩充的明细字段；未将后来抓取的数据塞回历史样本。

## 5. 保留的限制与未验收事项

- 用户明确暂缓的两个 F02 问题仍保留。单独复现为 **3 failed**：
  `test_specialist_isolation_publication.py` 的两个参数用例仍在原引用拒绝码断言失败；
  `test_structured_financial_delivery.py` 仍在最终 synthesis Agent 可用性断言失败。
  原因及暂缓决定见[F03 第 8 节](../plans/2026-10-21-f03-hypothesis-directed-checks.md#8-已知失败与阻塞2026-10-21)。
  阶段读取、最终正式记录和最终 Agent 输出可用性分别验收，不能相互替代。
- 310 项分层通过不是干净全量基线。未重复此前会持续访问本地代理的全量 pytest，也未改代理配置。
- 原数值口径与频率资格继续有效；新增字段或同日期条件不授权放宽已有比较/引用门禁。
- 自由解释的语义、原因、遗漏反证和模型分类仍需复核。未运行真实 `gpt-6-luna` 样本，
  因而没有分类服从度、真实成本、修复率或判断质量提升的结论。
- 本轮没有用户服务重启、Git 发布或用户数据迁移。F04 的输入选择、预算预留和成本目标仍需单独确认。
