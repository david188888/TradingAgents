# F04：可逆数值元数据去重设计

Status: Implemented offline; production deferred

**Do not use this document as evidence of current implementation behavior.**

日期：2026-10-22。接续[只读输入计量](../reviews/2026-10-22-f04-input-measurement.md)与
[整改待办 §4](2026-10-21-review-remediation-backlog.md#4-f04上下文与修复预算p2)。
用户已确认继续设计“可证明等价的重复表示去重”，保留全部经济信息，预算保持原样。
用户随后确认本方案的离线实施切片，已于 2026-10-23 完成；见[实施验收](../reviews/2026-10-23-f04-metadata-view-validation.md)。
生产接入及模型效果验收仍不在本切片内；当前行为以[计量契约](../contracts/native-input-measurement.md)及代码为准。

## 1. 目标与不可替代的验收

目标是只减少重复表示，不按重要性筛选事实，也不删去来源、反证、资格、限制或数值信息。
数据可逆性与模型使用效果分别验证：

1. **数据不变**：解码候选 model context 后，其排序紧凑 JSON 必须与原 model context 完全相同。
   保留字符串精度、期间、单位、所有实体绑定、集合及列表顺序。语义相近、舍入相等或仅 ID 相等都不够。
2. **范围不变**：原数值/F02/引用校验仍消费 canonical context。别名不能授予新事实权限，不能跨任务共享证据池。
3. **用途不变**：独立核查只回答其命题，局部检查不能关闭经济风险；保留全部已提供的限制与反证。
4. **成本诚实**：测量完整 prompt 的 UTF-8 字节，包含新增引用字段、协议标记和模型说明。
   不把 JSON 变小等同于 token、计费或质量改善。
5. **运行边界**：第一实施切片仅提供纯 codec 和离线对照；不接入生产 `_prompt()`，不变更
   `native_identity`、kernel、恢复、Reader、模型预算或服务配置。生产启用是后续独立的运行策略变更。

## 2. 当前代码的可核对关系

`research/numeric_narrative.py:prepare_numeric_context()` 先生成任务范围内的 `numeric_catalog`，随后：

```text
numeric_aliases[n_iiii] = numeric_catalog.anchors[i].anchor_id
numeric_meta[m_iiii]   = numeric_catalog.metadata[i]
```

`research/numeric_integration.py:_validate_public_context()` 再次按该规则核对别名。
`execution/native_model.py:_prompt()` 在现有引用别名、综合压缩与修复章节选择之后序列化 model context。
`numeric_catalog.metadata` 与 `numeric_meta` 在此 model context 中仍保存同一套完整元数据。
本轮选择去掉这份可逐项确认的副本；`numeric_aliases`、anchors、来源与 F02 observations 均保留。

必须在**同一个任务、同一个 phase、完成现有变换后的 model context**中比较两份元数据。
不能把 canonical ID 的副本与已翻译为短引用的副本混比，也不能跨运行或角色共享它们。

## 3. 两种可选方案

| 方案 | 变化 | 好处 | 限制 |
| --- | --- | --- | --- |
| A：复用既有元数据别名（推荐） | 完整对象只留在 `numeric_meta`，目录保存有序的 `metadata_aliases` | 使用现有 `m_` 别名，往返证明较小，范围与失败原因可枚举 | 字节收益有限，仍需验证模型使用效果 |
| B：进一步共享 anchors 的公共属性 | 对重复的 metadata、lineage、限制等另建共享表，anchors 使用引用 | 可能覆盖更大的重复体积 | 增加新的查找层次、跨字段恢复及模型说明；没有本轮可核对的成本/服从度证据 |

推荐先实施 A 的离线切片。B 不在该实施切片内，不以它的潜在收益为 A 设定验收承诺。
本设计也不包含事实筛选、自由文字摘要、来源截断、字段缩写、二进制压缩或外部引用解析。

## 4. A 的输入表示

候选名称为 `lossless-numeric-metadata-v1`，这是**离线候选协议**，不是已冻结的新运行身份。

```text
原 model context:
  numeric_catalog.metadata = [完整元数据甲, 完整元数据乙]
  numeric_meta             = {m_0000: 完整元数据甲, m_0001: 完整元数据乙}

候选 model context:
  prompt_context_view      = lossless-numeric-metadata-v1
  numeric_catalog.metadata_aliases = [m_0000, m_0001]
  numeric_meta             = {m_0000: 完整元数据甲, m_0001: 完整元数据乙}
```

`metadata` 与 `metadata_aliases` 不同时存在。其余所有 context 内容与输出 schema 保持原样。
候选只改变模型看到的输入表示；模型输出仍使用现有 `{{meta:m_alias}}`，不产生新的输出 ID 种类。
完整元数据中的 `meta_id`、kind、原文字、fact/evidence 引用等字段均保留，不能只留下展示文本。

候选提示词追加的说明冻结为：

> Numeric metadata are defined once in numeric_meta. numeric_catalog.metadata_aliases preserves their order; each entry names that exact m_ alias. Use the existing {{meta:m_alias}} tokens unchanged.

该段是代码拥有的协议说明，不是来源材料。测量必须把它前面的换行一起计入。

### 4.1 编码前提

- 输入必须是来自已核对哈希的原 model context，尚未带候选协议标记或 `metadata_aliases`。
- `numeric_catalog` 与 `numeric_meta` 的形状必须合法；原目录继续满足 canonical numeric catalog schema。
- 元数据别名集合必须恰好为按目录长度生成的 `m_0000`、`m_0001` 等，不接受额外或缺少的别名。
- 对每个 i，目录 metadata[i] 与 numeric_meta[m_iiii] 的排序紧凑 JSON 必须相同。
  原始对象不同、绑定不同、值类型不同或顺序不同都不得视为可共享。
- numeric policy 必须是已支持的 `anchored-narrative-v1`；未知 policy 是错误，不以 no-op 掩盖。
- 只有 `numeric_narrative_policy`、`numeric_catalog`、`numeric_meta`、`numeric_aliases` 及候选专用字段
  全部缺失的普通非数值 context 才是 `not_applicable`。任一数值组件出现就必须检查完整数值结构；
  缺失 policy、显式 null、未知 policy 或部分字段缺失均为错误，不按非数值输入略过。

### 4.2 解码约束

- 只解析已知 `prompt_context_view`，不得实现任意 `$ref`、JSON pointer、文件或网络引用。
- 候选目录必须有有序 `metadata_aliases`，且不得残留完整 `metadata`。
- `metadata_aliases` 必须是严格的 `list[str]`，恰等于 `[f"m_{i:04d}" for i in range(N)]`；
  `numeric_meta` 的键集合必须恰等于该列表的集合。不依赖 JSON 对象的插入顺序，不允许类型强转；
  拒绝未知、重复、跳号、错序、额外或缺失项。
- 按该列表逐项复制完整元数据，恢复原 `metadata`，删除候选专用字段，然后校验恢复目录的 canonical schema。
- 编码后立刻解码，并与原 model context 做完整 JSON 相等及内容哈希核对。
  不通过时该候选不可用，禁止把它计入压缩成功或信息保留率。
  单独 decoder 只能验证结构与引用；文本截断、值类型或内容篡改须由持有原件的往返比较发现，
  不能声称 decoder 能证明一个结构合法对象的历史真实性。

### 4.3 合法 no-op 与错误的区别

codec 只负责验证并生成可逆候选，不判断完整 prompt 的收益。合法空元数据输入返回 `empty_metadata`，
符合 §4.1 严格边界的普通非数值输入返回 `not_applicable`；两者保留原表示。
比较脚本计入所有协议开销，只有完整 prompt 的净字节收益为正才采用候选。
候选没有净收益时，最终决定为 `nonbeneficial`，有效 prompt 保持原表示、原哈希，不加标记或候选说明。
这些 no-op 均不能标为压缩成功。
别名关系错误、协议冲突、未知版本、目录或往返失败均为错误，不通过自动退回原表示来隐藏问题。

## 5. 离线实施切片与 ownership

1. `execution/native_prompt_view.py`：纯编码/解码；输入为普通 JSON model context，返回独立副本及
   `candidate` / `identity_noop` 的结果与封闭原因码，no-op 原因只含 `empty_metadata` / `not_applicable`。
   非空合法输入即使候选更大也返回候选，完整 prompt 收益决定由比较脚本拥有。
   无 ledger、SDK、Web、取数或持久化依赖，不拥有生产启用条件，不调用或改变 canonical 数值/F02/引用校验。
2. `scripts/compare_native_prompt_views.py`：复用现有 `capture_contexts()`、prompt builder 与 committed
   artifact reader。先核对原 kernel/prompt hash，再在独立副本中比较候选；重建完整候选 prompt，
   计算其净字节收益并选择 packed/no-op。stdout 只输出哈希、决定、计数与大小，不导出原文、提示词或凭据。
   报告同时保留候选大小及实际采用大小，只有采用时有效 prompt 才带候选标记和说明。
3. 现有 `native-input-inventory-v1` 不改规则。比较原 schema/context 与**候选解码后**的 schema/context。
   packed 的原始路径变化不能被包装成原清单直接通过。只有完整往返相等才允许报告还原保留率为 1。
4. 既有 profile 和 synthesis replay 的默认行为及输出口径不变；候选工具不冒充已有真实运行的输入或用量。
   无法读取、上游缓存缺失或原哈希不符时显式失败，不补跑模型或核查。

候选工具按实际 prompt 的结构化 JSON 边界替换 context，在原末尾附上候选说明；schema 和既有说明不变。
来源 JSON 内的 `Schema:` 或其它标记不得成为分段依据。每个 main/repair 独立处理，包括综合分段修复；
已保存但未派发的 repair 单列。未知 SDK 用量保持 null，候选 SDK tokens 始终未知。
CLI 沿用 `--run-id` / `--runs-root`，输出带独立 `schema_version`；退出码 0 表示原哈希、
候选验证和对照完整，1 表示对照不完整或候选失败，2 表示运行读取或重建失败。
失败样本保留在报告中并给出封闭原因码，不能从样本集合删除来制造完整对照。

### 5.1 生产接入的后续边界

本切片不会给新运行自动加该 policy。若后续批准接入，必须先冻结运行策略，再统一更新
native identity、kernel input 身份、numeric receipt input identity、Reader 的 expected input、
阶段读取、恢复及 profiler；缺策略的历史运行继续生成原提示词，不迁移保存数据。
不能只改 `_prompt()`，也不能以通过离线往返来省略模型效果验收。生产接入不属于本切片的交付条件。

## 6. 设计探测与收益边界

探测记录：[机器证据](../reviews/2026-10-22-f04-metadata-dedup-design-probe.json)，SHA-256：
`228a64eac50c5d0b6cd406b0511213c6b3f8fb9e416a26bbfbd57ad92a995d51`。
设计探测当时仅在内存中替换表示，尚未创建可调用 codec，未改 SDK 输入或生产文件。

样本包括此前宁德/江淮的 15 份已保存 main/repair prompt（其中 14 份实际派发）及
5 份带 F02/F03 和 fresh prompt-view 标记的合成输入。所有 20 份：
两套元数据相等，候选解码与原 model context 完全相等，恢复后的清单保留率为 1。
这不是 20 个模型质量测试，也不是候选格式服从度验收。

| 样本口径 | 基线完整 prompt 字节合计 | 采用正收益候选后的减少 | 比例 |
| --- | ---: | ---: | ---: |
| 两个历史运行的 14 个已派发账本条目 | 4,363,173 | 213,267 | 约 4.89% |
| 新契约合成样本的 5 个账本条目 | 559,794 | 32,652 | 约 5.83% |

以上已扣除候选标记、别名列表及新增说明开销，是字节假设对照，不是 token 或费用减少。
宁德经营 main 为 9,453 字节（约 2.86%），江淮经营 main 为 25,903（约 6.20%），
江淮回应 main 为 31,738（约 7.20%）。一个合成事件输入只有 1 个 metadata，候选反而增加 87 字节，
因此推荐保持原表示；上表已按 no-op 计为节省 0。
历史与新合成样本的证据不同，两行不能作为新旧策略成本对照。

## 7. 离线验收标准

设计时定义的关闭条件如下；codec 回归与实际离线结果已另记于实施验收，不能以设计探测代替：

- 所有固定正向样本编码/解码的完整 JSON 相等，恢复后 inventory 保留率为 1；原输入和文件树不变。
- 未知/重复/缺少/额外/错序的 alias、不同 metadata、重复 meta_id、残留 metadata、协议标记冲突、
  非法 catalog、值类型改变、截断文本及往返篡改全部拒绝，不静默降级。
- 负向数值/F02/引用反例仍被原 gate 拒绝；恢复不改单位、期间、精度、绑定、反证和作用域。
- 合法空目录、严格不适用的非数值 context、完整 prompt 净收益为零/负时保持原表示，原 prompt hash 不变；
  小目录按实际净收益判断，各类 no-op 不算候选采用。
- main、repair、分段 synthesis repair 分别核对，并对来源中的 JSON 标记注入做边界测试。
- 未知用量、失败、重试及未派发的保存修复仍单列；不把账本授权当作 SDK 送达或计费。
- 原两个真实运行和新合成夹具的候选采用项有正净字节收益；总有效输入不增大。
  不预设真实 token 或质量改善，也不以本局部目标关闭 F04 的整体成本目标。
- 比较脚本、codec 专项与原 profiler/replay/benchmark 相邻回归、Ruff、文档检查及 diff 检查通过。
  不改前端，不需要新增浏览器或真实模型调用。

## 8. 用户已确认的决定

用户已确认 **A 的离线实施切片**：只共享已经相等的元数据副本，保留全部信息与预算，
净收益不足时保持原表示。先交付可逆 codec、拒绝反例与完整 prompt 对照，不默认启用生产。
模型是否读得同样好仍需后续明确模型、样本与预算的验证；本次不据离线等价给出该结论。

## 9. 设计复核状态

2026-10-22 独立只读复核通过。首轮发现的三项阻塞已修订并经第二轮复核确认：
完整 prompt 收益由比较脚本决定；`not_applicable` 只允许所有数值组件均缺失；
小目录按实际净收益决定。另明确 alias 严格类型及顺序、原件对照的篡改检测责任与失败样本保留。
探测文件哈希、20 个样本及两组汇总均已核对；文档检查与 `git diff --check` 通过。
设计复核不代表 codec 回归、模型效果或生产启用验收；用户已审阅并批准离线实施。

## 10. 实施步骤

1. 新增纯 codec：严格 JSON/schema/policy/alias 校验、独立候选副本、解码与原件相等校验；
   以范围、精度、顺序、类型、篡改及合法 no-op 的专项反例验证。
2. 新增独立比较脚本：复用只读检查点和内存重建入口，逐 main/repair 验证原哈希；
   结构化定位 JSON，替换 context 并计入协议说明，报告候选和有效完整 prompt 大小及失败样本。
3. 用新契约合成夹具验证禁止网络/SDK/store、幂等与文件不变、未知用量、修复与未派发样本；
   用相同 canonical gate 验证解码不会放宽数值、F02 或合法引用限制。
4. 运行两个历史运行与新合成样本的离线对照，保存只有哈希/计数/大小的机器报告，
   同步当前契约与整改进度，运行专项及相邻 pytest、Ruff、文档与 diff 检查。

实施当时流程引用的 `writing-plans` 技能未安装，本节直接记录已批准方案的实施顺序与验收，
不新增设计范围、运行策略或模型调用。2026-10-23 已在本机补齐该技能及必要流程依赖并验证引用；
这是编码 Agent 环境修复，不是 TradingAgents 的运行依赖，也不追认当时执行过该技能流程。
