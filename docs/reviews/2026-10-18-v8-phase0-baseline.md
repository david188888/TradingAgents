# V8 Phase 0：离线基线与综合输入复现

Status: Historical

**Do not use this document as evidence of current implementation behavior.**

本记录是 2026-10-18 的核查快照，基于 `main@e8c283d` 和本地已保存运行。
当前工具边界见[基线合同](../contracts/evidence-benchmark.md)，目标见
[V8 提案](../plans/2026-10-17-evidence-reasoning-architecture-v8.md)。

## 目标与不变量

第一步要区分三个问题：模型综合是否成功交付、证据能支持哪些判断、判断是否准确。
综合失败只能回答第一个问题，不能直接证明证据不足，也不能反过来保证修复后应当看好。

本轮只增加离线诊断与评测工具。历史运行目录只读，原检查点、发布记录和未知派发保持原样；
没有模型/供应商请求、服务重启、运行归档、Git 发布或产品研究流程改动。

## 已完成

- `scripts/eval_benchmark.py`：按已提交事件读取内容寻址产物并校验 SHA-256，输出
  Markdown/JSON，区分交付、立场、计量缺失与模型分组。
- 固定 `hypothesis-quality-v1` 四轴 rubric。尚未进行人工主观评分，空值不当作零。
- `scripts/replay_synthesis_input.py`：复制检查点至内存，沿现有内核重建综合输入，
  校验缓存提议与数值收据，在综合调用前终止，只输出哈希。
- 8 份已交付 V7 运行的综合输入 **全部精确复现**；8/8 重建 SHA-256 与保存值一致。
- 当前条件绑定失败已有 `evidence_rejection` 分类及回归测试；旧运行的
  `missing_configuration` 是历史事实，不应据此重复修改当前实现。

## 确定性基线

共找到 9 份 V7 检查点：8 份进入综合并交付记录，另 1 份在综合前失败。
综合成功率为 0/8；综合前失败单独保留，不能从运行失败率中消失。

| Run 后缀 | 股票 | 模型 | 已计量输入 token | 修复及重试 / 实际模型尝试 | 综合输入哈希一致 |
| --- | --- | --- | ---: | --- | --- |
| ed080e23 | 600418.SS | gpt-6-luna | 601209 | 2/10 | 是 |
| 6aa5cb54 | 600418.SS | gpt-6-luna | 555296 | 2/7 | 是 |
| e02eb806 | 600418.SS | gpt-6-luna | 435587 | 2/8 | 是 |
| e7e64d35 | 600418.SS | gpt-6-luna | 507570 | 1/6 | 是 |
| 4f4bc126 | 600418.SS | gpt-6-luna | 563557 | 2/9 | 是 |
| 497cd6e7 | 600418.SS | gpt-6-luna | 304740 | 1/7 | 是 |
| c8e16c69 | 600418.SS | gpt-6.1-sol | 834682 | 2/8 | 是 |
| 107ea6cd | 300750.SZ | gpt-6-luna | 710872 | 3/10 | 是 |

综合前失败的 `c6acb6ac`：gpt-6.1-sol，已计量输入 139198 token，修复及重试 1/4。
它不是第九次综合失败。表中模型、历史策略不同，不应把样本合并成预测质量比较。

宁德时代 `run_20261017T075032860279Z_107ea6cd`：

- 已计量输入 710872、输出 8092，共 718964 token；10 次模型尝试仅 9 次有保存用量，
  因此真实总消耗仍未知。提案的约 728K 输入与“3/11”不作为精确计数沿用。
- 综合及修复占已计量总 token 的 34.15%，不代表真实总消耗的精确占比。
- 175 条事实，17 条被假设引用（9.71%）；保存指标 6 项，定向核查记录 0 项。
  固定局部证据检查另行计数，不能由此说所有代码检查均未执行。
- `report_status=specialist_summary`、无总体立场；失败依次为
  `numeric_anchor_scope`、`adjudication_coverage`。
- 保存与重建的综合输入哈希均为
  `05498fd497c590f080a7f12b65f68fa2244e3de5f83ac88753c5150b8bd901aa`。

计数源、诊断码和全部输入哈希保存在[机器可读快照](2026-10-18-v8-phase0-baseline.json)。
该文件仅包含测量结果，不包含原始证据、模型响应、提示词或凭据。

## 验证

- 新工具回归与现有条件错误分类回归：13 项通过。
- 全包/CLI 及本轮脚本、测试的 Ruff 通过；Agent 文档检查通过；`git diff --check` 通过。
- 真实历史输入复现：8/8 完全一致，未调用模型。
- 未运行前端或完整 Python 回归：本轮没有修改产品前后端代码。
- 这不是 Phase 0 验收完成；没有新的三公司实测，没有综合成功或研究质量改善的结论。

复现命令：

```bash
python scripts/eval_benchmark.py --workflow evidence-production-v7 --format json
python -m scripts.replay_synthesis_input --run-id run_20261017T075032860279Z_107ea6cd
python -m pytest tests/test_eval_benchmark.py tests/test_replay_synthesis_input.py tests/web/test_single_run_manager.py::test_condition_evidence_failure_is_not_classified_as_missing_configuration -q
```

## 继续之前的确认点

V8 第 9 节第 9 项尚未确认：是否允许额外 1 次宁德时代 `gpt-6-luna` 订阅运行，
并在显式开发开关下把综合失败的最终结构化响应保存在仓库已忽略的本地调试目录。
建议只捕获综合的最终响应文本，不捕获模型内部推理；默认关闭，不进入公共运行记录，
不进入 Git。先取得失败样本，再制作脱敏回归并落实分段校验/修复。

调用预算 14/18、`research-record-v2` 退役旧接口，以及 Claude rubric 评分者替换，
属于后续阶段确认点，本轮没有替用户决定。

仍待推进：失败响应采集与触发条件定位、综合分段、数据资格与标题清理、稀疏样本采集、
供应商结构化输出探测及 Reader 修复。模型失败响应缺失时，不能根据封闭诊断码猜测
具体错误内容并宣称根因已修复。
