# F04：可逆元数据表示的离线实施验收

Status: Completed for the approved offline slice

日期：2026-10-23。用户确认[方案 A](../plans/2026-10-22-f04-lossless-metadata-view.md)后实施。
当前接口及边界见[输入计量契约](../contracts/native-input-measurement.md#offline-reversible-metadata-comparison)。
本记录不代表整个 F04、模型效果或生产策略已经验收。

## 交付与判定原则

- `tradingagents/execution/native_prompt_view.py`：纯 JSON codec，只共享已经逐项确认相等的元数据副本。
  使用现有 `numeric_meta` 和有序 alias 列表；保留全部其余内容，严格校验 canonical catalog、
  数值 policy、metadata/anchor 别名、类型及顺序。解码后完整 JSON 与原件相等。
- `scripts/compare_native_prompt_views.py`：从 committed checkpoint 在内存中重建，每个 main/repair
  先核对原 context/prompt hash，再独立变换实际 model context。完整成本含 schema、既有说明、
  新标记、alias 列表及新增说明前的换行。净收益不为正时有效 prompt 与原哈希保持相同。
- 解码器只证明结构与引用合法；持有原件的完整 JSON 对照负责检测内容篡改。
  inventory 只比较解码后的原路径，不能用压缩后的路径变化放宽保留条件。
- 不完整的数值组件、未知 policy、错误 alias、非法目录及往返失败均报告错误，不静默 no-op。
  合法空目录、完全非数值 context 及无净收益候选分别报告原因。
- 失败样本保留在集合与计数中，字节合计明确只包含完成对照的样本；未知、重试及孤立用量不伪造。
  未派发的保存修复单列。输出只含哈希、ID、决定、大小及计数，不导出原始文本或配置凭据。

本切片不改 `_prompt()`、生产调用、运行身份、kernel、恢复、Reader、预算或用户数据。
无模型/数据提供方请求，无服务重启；未进行 Git 发布。沿用当前 checkout，保留其他未提交工作。

## 可复核的机器结果

[完整报告](2026-10-23-f04-metadata-view-comparisons.json)，SHA-256：
`38a0c66522e75ed9f5e24c36107873ba1815b89ba1fe900887f9916bb4462c1c`。

| 样本与口径 | 条目 | 基线完整 prompt UTF-8 字节 | 有效候选字节 | 减少 |
| --- | ---: | ---: | ---: | ---: |
| 宁德历史运行，派发账本条目 | 7 | 1,710,602 | 1,670,351 | 40,251（2.35%） |
| 江淮历史运行，派发账本条目 | 7 | 2,652,571 | 2,479,555 | 173,016（6.52%） |
| 两个历史运行合计，同口径 | 14 | 4,363,173 | 4,149,906 | 213,267（4.89%） |
| F02/F03＋fresh prompt 标记合成输入，账本条目 | 5 | 559,794 | 527,142 | 32,652（5.83%） |

另保留江淮 1 个已保存但未派发的综合 repair。共 20 个已保存 prompt（历史 15＋合成 5），
全部原哈希核对、候选完整还原及解码后 inventory 保留率为 1。一个合成事件输入只有一个 metadata，
候选增加 87 字节，最终为 `nonbeneficial`，有效输入及其哈希不变；其余 19 份选择候选。
报告区分所有 prompt 样本与按账本派发次数加权的口径，不把二者相加。

历史结果与[设计探测](2026-10-22-f04-metadata-dedup-design-probe.json)的总数及收益一致。
合成输入由临时隔离 RunStore 及确定性测试 caller 生成，生成后用正式比较 API 测量，临时目录已退出。
临时生成所需的文件写入不属于只读比较命令；用户历史运行仅使用只读入口。
合成 caller 的账本派发不代表 SDK 请求；候选 SDK tokens 始终为 null。
这些字节结果不是 token、费用或质量改善证据，新旧策略两组也不是受控模型成本对照。

## 验证

专项 codec 44 项、比较工具 16 项，覆盖：严格 JSON 类型、非有限数、alias 缺失/额外/重复/错序、
未知协议、schema 错误、目录副本不相等、精度/绑定/范围/列表顺序/文本篡改、空目录及完全非数值输入、
完整 prompt 净收益为零/负、来源内 JSON 标记、普通修复与综合分段修复、未派发保存修复、失败/重试/
孤立用量、错误原哈希、缺失上下文、缺失缓存、artifact 哈希及 CLI 0/1/2。
测试阻止构造 SDK client/RunStore、网络请求及模型派发，并核对输入深拷贝与文件树不变。
原数值、F02 与引用 gate 对同一负例在还原前后拒绝一致；没有修改这些 gate。

```bash
python -m pytest tests/test_native_prompt_view.py tests/test_native_prompt_comparison.py \
  tests/test_native_input_profile.py tests/test_replay_synthesis_input.py \
  tests/test_eval_benchmark.py tests/test_numeric_narrative.py \
  tests/test_factual_premises.py tests/test_synthesis_reference_surface.py -q
```

结果：**150 passed**。报告字段命名收紧后另复验比较工具 **16 passed**。
出现 1 条既有 Starlette/httpx deprecation warning，不影响结果。
全包/CLI Ruff 与本切片 scripts/tests Ruff 通过；文档和 diff 检查通过。
本切片未改前端，不新增浏览器、构建或真实模型验收。

## 仍未完成

此切片只关闭可逆表示与离线对照工具。整个 F04 尚需分别决定与验收：

1. 是否推进生产 policy/identity、收据输入身份、Reader、恢复及历史兼容的一致接入。
2. 固定模型、证据、对照策略和预算后的真实 tokens、候选格式服从度、修复率、交付及 F07 质量。
3. 综合修复预留、剩余额度借用、早期失败、恢复及并发政策，以及预先冻结的成本目标。

没有以 JSON 可逆替代经济信息完备、推理质量或研究结论的语义验收；没有关闭待办中的这些项目。
