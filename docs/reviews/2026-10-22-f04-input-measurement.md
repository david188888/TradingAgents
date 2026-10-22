# F04：只读输入计量与保守保留清单

Status: Historical

**Do not use this document as evidence of current implementation behavior.**

日期：2026-10-22。用户在完成 F02 接力修复后，确认先实施“只读输入计量＋必需证据清单”。
本次只交付该切片。当前行为见[计量契约](../contracts/native-input-measurement.md)，
后续仍由[整改待办 §4](../plans/2026-10-21-review-remediation-backlog.md#4-f04上下文与修复预算p2)跟踪。

## 1. 目标、不变量与实现

首先回答“实际给模型送了什么、重复在哪里、哪些内容不能无声丢失”。
保持生产输入、canonical 校验、保存证据、历史身份、原有修复/总尝试上限不变。
没有压缩、模型/供应商调用、用户服务重启、Git 发布或用户数据迁移。

- `scripts/replay_synthesis_input.py` 提取了共享的内存输入捕获函数，沿真实 kernel 恢复各阶段上下文。
  保留原 synthesis hash 诊断接口；缺上游缓存时拒绝，不为缺失工作补跑模型或核查工具。
- `scripts/profile_native_inputs.py` 读取 committed checkpoint 并核对文件哈希，检查 kernel input hash；
  使用已有 prompt builder 按保存版本在内存渲染 main/repair，再逐一核对保存的提示词 SHA-256。
  数值校验用的缩减 context 不是完整 prompt，未拿它冒充成本输入。
- 分离 canonical context、实际 model context、schema/说明、UTF-8 字节与字符、保存 tokens、未知用量。
  同一 usage key 只计一次；失败/重试保留；无匹配账本的用量单列。
  账本派发、SDK main marker、提示词保存、网络交付和计费不能混为一个计数。
- `scripts/native_input_inventory.py` 提供 `native-input-inventory-v1` 保守清单及纯比较函数。
  实体的 ID/文字/数值/期间/来源/限制保持原绑定，按作用域存摘要。默认不输出原文或 prompt，
  `--include-inventory` 输出逐项 scope、ID、哈希；不输出配置凭据。

## 2. 样本与冻结材料

[机器测量 JSON](2026-10-22-f04-input-measurements.json) SHA-256：
`17af61ba58a9b613e6c9ecd759fe24d30c9ea74305787db7be49977c0f160548`。
文件保存各样本策略、模型、checkpoint 内容摘要、阶段 input/prompt hash、输入组成、保留清单摘要和用量行。
checkpoint 内容摘要采用排序紧凑 UTF-8 JSON；读取时的 artifact 文件哈希另外由已有 reader 验证。

| 样本 | 来源 | 可作何种证据 |
| --- | --- | --- |
| 宁德 `run_20261018T160807562817Z_6ae06213` | F02/F03 前的已保存真实运行 | 历史策略的准确输入/用量分解 |
| 江淮 `run_20261018T161117240227Z_021254c5` | F02/F03 前的已保存真实运行 | 同上，含定向回应和两次早期修复 |
| `run_20261022T120125694935Z_e393f9bf` | `tests/test_native_input_profile.py` 的合成 F02/F03 临时夹具 | 当前契约的计量与清单覆盖，不能证明真实模型服从度或成本 |

合成样本只在临时目录构造，随后删除临时运行目录；未写入用户运行库。
它使用 `factual-premises-v1`、`hypothesis-directed-checks-v1`、`anchored-narrative-v1`，
并固定当前 fresh V7 的 prompt-view 标记，离线渲染提示词后保存到夹具内存。
其“哈希匹配”只核对这份离线夹具，不是一次真实 SDK 请求的复现。
5 项账本派发均没有真实 SDK tokens，输入和输出均保持 null；不记零。
该夹具不代表扩充 11 个字段后真实供应商采集的长度，也不代表稀疏/冲突样本的完整运行。
首轮 fixture 曾未冻结 fresh prompt-view 标记，已修正后重新生成本记录，未把早期输出当作现策略基线。

## 3. 历史真实样本测量

两个运行各 7 个已派发账本条目的提示词哈希均匹配，共 14/14；对应 tokens 全部有保存值。
这些 tokens 与既有 benchmark 一致，没有新增模型请求。
下表按阶段合计主调用、修复与重试的已保存 **输入 tokens**；未调用阶段为“不适用”，不是零用量失败。

| 阶段 | 宁德 | 江淮 |
| --- | ---: | ---: |
| 经营专项 | 208,776 | 265,776 |
| 事件专项 | 39,795 | 17,861 |
| 市场专项 | 25,078 | 不适用 |
| 挑战 | 162,304 | 174,935 |
| 定向回应 | 不适用 | 304,786 |
| 综合 | 101,102 | 109,778 |
| 合计 | 537,055 | 873,136 |

两个运行分别有 2 次已派发修复。宁德修复输入共 117,019 tokens，江淮共 285,373 tokens；
不能据此认定移除修复可保留质量，修复有其合法用途。
江淮还保存了综合 repair prompt，其哈希可重建，但对应已派发次数为 0；
提示词存在不能被计作已执行修复，也不能据此声称综合得到修复保障。

以下为 **main prompt UTF-8 字节**，不是 tokens 或费用：

| 阶段 | 宁德总 prompt | 江淮总 prompt |
| --- | ---: | ---: |
| 经营专项 | 330,730 | 417,879 |
| 挑战 | 494,981 | 519,931 |
| 定向回应 | 不适用 | 440,731 |
| 综合 | 334,752 | 353,062 |

经营 main prompt 中，宁德 numeric_catalog 为 131,768 字节（约 39.8%），sources 为 94,411（约 28.5%）；
江淮分别为 175,635（约 42.0%）及 117,107（约 28.0%）。江淮回应中的目录为 196,290（约 44.5%），
来源为 118,243（约 26.8%）。这些是组成体积，不能把整块目录或来源认定为冗余。

在“完整字符串至少 64 UTF-8 字节且完全相同”的明确口径下，宁德经营 model context 的重复字符串负载
为 44,557 字节，江淮为 57,830 字节。它不统计重复键/相似子串，也不是安全可删除量或 token 节省承诺。

## 4. 新契约合成清单与边界

新夹具 main prompt 的 UTF-8 字节分别为：经营 130,994、事件 19,263、挑战 147,671、回应 125,309、
综合 136,557。其对应保守清单分别有 553、251、675、428、650 个去重单元。
样本、证据量和输入不同，不能与上一节历史样本相减后声称 F02/F03 变便宜。

首版清单按每个任务保留全部已提供 schema/context：

- 事实、来源原文/片段、披露时点、资格、限制与冲突；数值单位/期间/精度/lineage。
- F02 observations、解释边界、待验证问题，及数值 aliases/meta、合法 ID/条件/维度范围。
- 原假设和反证、挑战独立命题、输入需求、任务去向、计算结果与仅命题作用域。
- 回应的分配对象及逐挑战事实范围；综合裁决、章节要求及其允许引用集合。
- 修复按自身准确 schema/context 单独建清单，不能用缩窄的 repair 清单替代整个 main 任务的要求。

这是保守保留底线，不是已证明的最小充分集，更不代表全部经济事实都已进入原输入。
只有同作用域内完全相同的实体表示可在当前比较中共享一项要求；跨作用域的副本不能代替允许事实。
未来若改变结构或去掉重复表示，需要单独设计可证明的等价保留规则，并继续通过原来的数值/F02/引用门禁。
清单保留率为 1 只证明该内容比较，不证明自由文字语义、反证完备性或判断质量。

## 5. 验证

```bash
python -m pytest tests/test_native_input_profile.py tests/test_replay_synthesis_input.py \
  tests/test_eval_benchmark.py -q
ruff check tradingagents cli scripts/check_agent_docs.py scripts/eval_benchmark.py \
  scripts/replay_synthesis_input.py scripts/profile_native_inputs.py \
  scripts/native_input_inventory.py tests/test_native_input_profile.py
python scripts/check_agent_docs.py
git diff --check
```

最终专项与相邻诊断共 **34 passed**。覆盖：
不构造 RunStore/模型客户端、不发网络请求、输入不变、确定性结果、committed artifact 哈希拒绝、
临时文件树读取前后相等、缺缓存拒绝、kernel/prompt hash 不符、JSON 标记注入、多字节字符与分解守恒、
失败/修复重试/未知用量、重复匹配，以及删原文、删限制、换期间、数值舍入、反转观察、删挑战、
改事实绑定/允许集合、跨作用域搬移等负向反例。Ruff、文档与 diff 收尾检查另行运行。
未改前端或生产运行模块，因此本切片没有新增浏览器验收或重新构建 SPA 的必要。

## 6. 后续仍需确定

测量已经能支撑下一轮设计，但没有解决 F04 的视图选择、综合修复预留/借用或成本目标。
建议先设计可以逐项证明等价的重复表示去重，保留全部经济信息及原有预算；
随后再讨论按经济重要性筛选证据与修复配额的取舍。不能把当前清单当成已经批准的压缩算法。
真实 F02/F03 样本、运行数和预算仍需另行确认，F07 的评分者及质量口径保持原约定。
