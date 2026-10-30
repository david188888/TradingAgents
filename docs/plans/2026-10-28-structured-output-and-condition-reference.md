# 结构化输出与条件引用修复计划

状态：四阶段代码已实施；一次授权真实研究为部分交付。实测发现的综合 schema 适配漏项已离线修复，修复后真实验收待授权
日期：2026-10-28
证据运行：`run_20261027T134950005438Z_1584d35d`（002130.SZ，workflow `evidence-production-v8`）

本文档分析两个长期未解决的交付阻塞问题，定位根因，并给出按顺序执行的实施计划。

---

## 1. 现象与实际诊断

用户报告的现象是：总体判断因数字绑定失败无法交付，独立挑战的条件引用连续失败导致有效挑战为 0 条。

从该次运行的检查点 `native.model_diagnostics` 读出的真实诊断如下。

| stage | phase | detail_code | 附加字段 |
| --- | --- | --- | --- |
| operating_quality | main | `numeric_manifest_binding` | — |
| operating_quality | repair | `numeric_manifest_binding` | — |
| synthesis | main | `numeric_manifest_binding` | `synthesis_reference_issues`（见下） |
| search_review.1.event_context | main | `gap_target_scope` | — |
| search_review.1.event_context | repair | `numeric_literal_unbound` | `field_name: new_risks` |

synthesis 阶段的 `synthesis_reference_issues` 分段真相：

| path | code |
| --- | --- |
| `dimensions.1` | `numeric_manifest_binding` |
| `adjudications.0` | `premise_observation_scope` |
| `adjudications.2` | `premise_observation_scope` |
| `overall` | `premise_observation_scope` |

`native_stages` 最终状态：`operating_quality: failed`，其余五段 `completed`，两个 response 段 `skipped`。

### 1.1 需要修正的一处既有判断

报告中「只有 overall 未通过，错误为 `numeric_manifest_binding`」与实测不符。`overall` 段的真实失败码是 `premise_observation_scope`，`numeric_manifest_binding` 是 stage 顶层诊断码，它被 main 阶段第一个失败分段（`dimensions.1`）覆盖后向上冒泡。

这本身就是一个独立缺陷：**顶层诊断码掩盖了分段真相**，导致人工排查从一开始就指向了错误的方向。本计划把它作为第 1 阶段的一部分处理。

### 1.2 本次运行未出现 challenge_condition_reference

在该检查点全文中搜索 `challenge_condition_reference`、`challenge_schema_invalid`、`proposal_schema_invalid` 三个字符串，命中数均为 0，`native_stages` 中 `challenge` 为 `completed`。

因此问题 2 的分析建立在**代码路径**而非本次运行证据之上。该失败在历史运行中出现过，其触发条件可从代码静态确认（见 3.2），但本计划无法用本次运行数据证明其复现率。这一点影响第 4 阶段的验收方式。

---

## 2. 问题一根因：根本没有启用结构化输出

### 2.1 事实链

本次运行 `llm_provider` 为 `chatgpt`，`quick_think_llm` 与 `deep_think_llm` 同为 `gpt-6.1-terra`，即全部阶段走 SIWC 订阅路由。

`tradingagents/llm_clients/chatgpt_client.py:85` 构造的请求体：

```python
payload = {"model": self.model, "input": [{"role": "user", "content": prompt}],
           "store": False, "stream": True}
if self.reasoning_effort is not None:
    payload["reasoning"] = {"effort": self.reasoning_effort}
```

没有 `text.format`，没有 `response_format`，没有任何 schema 约束字段。

JSON Schema 只是被拼接进了 prompt 正文。`tradingagents/execution/native_model.py:383` 附近：

```python
+ f"\nOutput language: {language}. Return one JSON object only, no Markdown.\n"
+ "Schema:\n" + schema + "\nSaved research context:\n" + payload
```

`tradingagents/llm_clients/capabilities.py` 中的 `supports_json_mode` / `supports_json_schema` / `preferred_structured_method` 能力表只被 OpenAI 兼容客户端消费，ChatGPT SIWC 这条路完全没有接入。`tradingagents/agents/utils/structured.py` 的 `bind_structured` 走 LangChain `with_structured_output`，而原生研究内核不经过它。

### 2.2 结论

模型是在**自由文本模式**下，凭 prompt 里的 schema 文字描述去猜一个深度嵌套的 envelope。该 envelope 在 `evidence-production-v8` 下同时叠加了：

- `inline-bindings-v1` 的就地引用结构（`model_binding_policy`）
- `evidence-packets-v1` 的证据包字段（`research_delivery_policy`）
- `SearchGapsV1` 的 gaps 数组（`SEARCH_WORKFLOW_VERSION`）
- `factual-premises-v1` 的 premise 绑定
- synthesis 阶段的分段请求 schema（`reference_schema` 版本 3）

`numeric_manifest_binding` 不是"某一层不匹配"，它是 `numeric_narrative.py` 中 `_schema_validate` 与 `_canonical_envelope` 在 Pydantic 校验失败时抛出的**统一错误码**。换言之：它就是 schema 校验失败本身，只是把所有形状问题折叠成了一个标签。

### 2.3 错误码当前覆盖的互不相同的失败

`numeric_manifest_binding` 当前同时表示以下五种情况：

| 位置 | 实际含义 |
| --- | --- |
| `_schema_validate` | proposal 不符合 stage schema |
| `_canonical_envelope` | envelope 外层 `{proposal, plans, structured_bindings}` 形状错 |
| `_compile` 开头 | `numeric_catalog` 缺失或格式错 |
| `_cutoff` | `numeric_analysis_date` 缺失或非 ISO 日期 |
| `_compile_field` synthesis 分支 | 父假设不存在或 `invalidation_index` 越界 |
| `validate_numeric_field` | 字段凭证或 catalog 回放校验失败 |

修正提示在 `_repair_prompt` 中对所有 `numeric_` 前缀码走同一分支，只给出"使用提供的 token、不要凭空编号"这类通用指导，无法定位到具体字段。

---

## 3. 问题二根因：字段无约束且修正提示无信息

### 3.1 字段定义

`tradingagents/agents/schemas/_native_stage.py:198`：

```python
condition_id: str | None = None
```

完全自由的字符串，无 pattern、无 enum、无长度约束。`ChallengeProposalV2` 与 `V3` 通过继承沿用该定义。

### 3.2 校验要求

两处独立校验，要求相同的两个条件同时成立。

`tradingagents/research/challenge_checks.py:211`：

```python
if proposal.condition_id and conditions is not None:
    condition = conditions.get(proposal.condition_id)
    if condition is None or condition["hypothesis_id"] != proposal.hypothesis_id:
        raise ChallengeValidationError("challenge_condition_reference")
```

`tradingagents/graph/native_research.py:410`：

```python
bound = conditions.get(item.condition_id) if item.condition_id else None
if item.condition_id and (bound is None or bound["hypothesis_id"] != item.hypothesis_id):
    raise ValueError("challenge selected a condition from another hypothesis")
```

即：ID 必须存在于 `conditions` 字典中，且该条件必须属于挑战自己声明的 `hypothesis_id`。

### 3.3 模型侧的实际难度

`native_research.py:368` 确实把完整 `conditions` 字典放入了 `critic_context`，所以模型能看到全部候选。但候选 ID 的形态是 71 字符 sha256：

```
condition.01a9b686b279e81f94ae1aa8cf4a0d3f8dd1fc3aab8b5ab6d1a1f74988fb1d47
```

本次运行有 12 个 conditions 与 6 个 hypotheses。模型需要同时做到：逐字符无误复制一个 71 字符哈希，并自行完成"该条件属于哪个假设"的交叉匹配。在自由文本模式下（见第 2 节），这两件事都没有任何机制保障。

### 3.4 修正提示缺失分支

`_repair_prompt`（`native_model.py:939` 起）为以下错误码准备了专门分支，每个分支都向模型提供精确的合法取值：

`challenge_review_coverage`、`inline_binding_shape`、`gap_cutoff_changed` / `gap_role_changed` / `gap_target_scope`、`dimension_claim_reference`、`condition_evidence_reference` / `condition_metric_reference`、`argument_reply_fact_reference`、`judgement_condition_reference`、`numeric_*`（通用）、synthesis 分段失败。

其中**没有 `challenge_condition_reference`**。因此该失败发生时，模型只收到通用的 `_REPAIR_INSTRUCTION`：

> Your previous response failed JSON/schema validation. Return one valid object using the original evidence and schema. Do not invent IDs or facts.

模型既不知道哪个 ID 非法，也不知道合法 ID 是哪些，更不知道约束是"必须属于同一假设"。这直接回答了原始问题中「修正提示是否提供了足够明确的合法引用信息」：没有。

---

## 4. 实施计划

四个阶段按顺序执行。每阶段独立可验证，前一阶段的产出是后一阶段的输入。

### 阶段 1：诊断分层（零契约风险）

**目标**：让错误码指向唯一根因，让顶层码不再掩盖分段真相。

1. 拆分 `numeric_manifest_binding`，按 2.3 表格的六个位置给出独立错误码。保留 `numeric_manifest_binding` 作为兼容别名，用于已冻结任务的回放。
2. 在 `safe_model_diagnostic` 中附加 Pydantic `ValidationError.errors()` 的 `loc` 路径。只保留结构位置，不保留 `msg` 与 `input`，以维持既有的「不保留模型文本」约束。
3. 顶层诊断码在存在分段真相时不再冒泡覆盖。`synthesis_reference_issues` 已有的结构推广到其他分段阶段，顶层码改为显示分段码的集合而非第一个。

**验收**：构造单元测试，对 2.3 表格的每一行各造一个最小失败输入，断言得到各自独立的错误码与预期 `loc`。

**影响面**：`tradingagents/research/numeric_narrative.py`、`tradingagents/execution/native_model_diagnostics.py`、`tradingagents/agents/schemas/_native_stage.py` 与 `_numeric_stage.py` 的错误码 Literal 列表。

### 阶段 2：修正提示携带精确位置

**目标**：修正一轮能拿到可操作信息，而不是通用训诫。

1. 基于阶段 1 的 `loc`，把 `_repair_prompt` 的 `numeric_*` 分支从通用指导升级为具体定位，形如「第 N 个假设的第 M 个条件缺少字段 X」。
2. 新增 `challenge_condition_reference` 分支，照 `judgement_condition_reference` 的既有写法，把「假设 → 其条件列表」的完整映射写入修正提示。

**验收**：单元测试断言给定诊断码与 `loc` 时，`_repair_prompt` 输出包含对应的合法取值列表。

**影响面**：`tradingagents/execution/native_model.py` 的 `_repair_prompt`。

注意：`_repair_prompt` 对已派发过的修正会按 sha256 校验 prompt 同一性（`native.prompt.<stage>.repair`），冻结任务的修正提示不得改变。新分支只在哈希不匹配且 `workflow_version` 属于当前集合时生效，与既有分支的处理方式一致。

### 阶段 3：条件引用改为两段式（选项 A）

**目标**：从结构上排除非法条件引用，而不是靠校验事后拒绝。

模型输出 `hypothesis_id` + `condition_index`（该假设下条件的序号），由程序查表生成 `condition_id`。这与 synthesis 阶段 `change_conditions` 已在用的 `{hypothesis_id, invalidation_index}` 模式一致（见 `numeric_narrative.py` 的 `_compile_field` synthesis 分支），是同一个已验证的路子。

索引是小整数，模型无需复制哈希，错误空间从任意字符串缩小到 `0..N-1`，且跨假设引用在结构上不可能发生。

需要同步修改的消费点（已全部确认）：

| 文件 | 行 | 当前用途 |
| --- | --- | --- |
| `tradingagents/agents/schemas/_native_stage.py` | 198 | 字段定义，V2/V3 继承 |
| `tradingagents/research/challenge_checks.py` | 211 | `validate_challenge` 校验 |
| `tradingagents/graph/native_research.py` | 410 | 挑战落库与任务生成 |
| `tradingagents/web/reader_stage_projection.py` | 230, 271 | Reader 阶段投影 |
| `tradingagents/web/reader_process_projection.py` | 503 | Reader 流程投影 |

兼容策略：`condition_id` 保留为可选输入并继续校验，新增 `condition_index` 为首选路径。两者同时出现时以 `condition_index` 为准并校验一致性。已冻结任务按既有冻结策略走 `condition_id` 旧路。

**验收**：单元测试覆盖「索引合法」「索引越界」「索引与假设不匹配在结构上不可构造」三种情形，以及 Reader 两个投影在新旧两种输入下的输出一致性。

### 阶段 4：Responses API 严格结构化输出

**目标**：形状失败在 token 级别不可能发生。

#### 4.1 前置未知项

OpenAI Responses API 支持：

```python
payload["text"] = {"format": {"type": "json_schema", "name": "...",
                              "schema": schema_value, "strict": True}}
```

strict 模式是约束解码，模型不可能产出违反 schema 的输出。

**但 `gpt-6.1-terra` 走 SIWC 订阅路由（`chatgpt_client.py` 的 `API_ORIGIN + "/responses"`）是否透传 `text.format`，无法离线确认。** 这是实施该阶段前必须先解决的未知项。

处理方式：先写一个最小探测脚本，用一个平凡 schema 向 SIWC 路由发一次实请求，观察是否被接受、是否生效。该探测需要真实凭证与一次网络调用，按项目约定属于需要显式授权的实测。

- 若 SIWC 支持：strict 模式对全部阶段生效。
- 若 SIWC 不支持：strict 只能用于 API-key 路由；SIWC 路由退回到阶段 1 至 3 的改进，并在能力表中显式标记该路由不支持 schema 约束，使降级是声明式的而非沉默的。

#### 4.2 Schema 适配层

当前 schema 不能直接用于 strict 模式。strict 的硬性要求与当前 schema 的冲突：

| strict 要求 | 当前 schema 现状 |
| --- | --- |
| 每个 object 必须 `additionalProperties: false` | Pydantic 默认不输出该字段 |
| 所有属性必须在 `required` 中 | 大量 `str \| None` 与 `default=()` 可选字段 |
| 不支持 `minLength` / `maxLength` | 大量 `Field(min_length=1, max_length=400)` |
| 不支持 `default` | `default=()` 普遍存在 |
| 嵌套深度与属性总数有上限 | v8 叠加五套策略后 schema 规模需实测 |

因此需要一个转换层：把 Pydantic 生成的 JSON Schema 转为 strict 兼容形态。按用户确认保留原字段类型：原本允许 `None` 的字段保留 nullable；默认空集合但不允许 `None` 的字段改为必填数组，无内容时输出 `[]`。不得把所有带默认值的字段统一转为 nullable。长度约束降级为 prompt 中的 schema 说明，仍由原 Pydantic 校验。

**Pydantic 校验保持完全不变**，strict 只负责把"形状"提前保证掉，长度等语义约束仍由事后校验兜住。`_alias_schema_choices` 对 `const` / `enum` 的动态改写在转换层之后执行，顺序不变。

**验收**：对每个 stage schema 断言转换结果满足 strict 的全部形式要求；断言转换后的 schema 与原 Pydantic 模型在合法样本上判定一致。实际启用需要一次授权的真实运行验收。

---

## 5. 不在本计划范围内

原始报告中的其余三个问题与本计划的两个问题根因不同，单独处理：

- 执行状态与报告完整性的表达不一致（「已完成」与「总体评级生成失败」并存）。阶段 1 的诊断分层会为其提供必要的区分能力，但表达层统一需要独立设计。
- 资料缺口对结论置信度的影响，以及哪些错误应触发有限重试。本次 `provider_response_unqualified` 被标为不可重试，网络超时等可重试故障下的线上行为尚未验证。
- 白话解释的覆盖验收单位。本次确认白话内容实际存在，但未证明所有应解释内容均已覆盖。

## 6. 执行顺序与风险

阶段 1 与 2 不改公共契约，风险最低，且为后两阶段提供诊断能力。阶段 3 改 `ChallengeProposalV1` 公共 schema，牵动 V2/V3 与五个消费点，需按既有冻结策略保证旧任务兼容。阶段 4 依赖一次需授权的真实探测，其结论决定该阶段的适用范围。

四阶段完成后，形状类失败（若 SIWC 支持 strict）在结构上消除，条件引用失败在结构上消除，剩余失败均有唯一错误码与精确位置，修正提示携带可操作信息。


## 7. 本轮实施与验证记录（2026-10-28）

- 阶段 1：六类失败分别使用 `numeric_proposal_schema`、`numeric_envelope_schema`、`numeric_catalog_invalid`、`numeric_cutoff_invalid`、`numeric_condition_reference`、`numeric_receipt_invalid`；保留旧 `numeric_manifest_binding` 回放路径。诊断只保留声明字段与索引，未知字段名脱敏。分段诊断使用 `section_validation` 加 `detail_codes` 集合，并保留 synthesis/专项/挑战的逐段路径。
- 阶段 2：修正提示附精确字段位置、合法数字/元数据别名与完整的假设→条件候选映射；已派发的修正优先匹配原提示词哈希。
- 阶段 3：新 V8 身份冻结 `challenge_reference_policy=hypothesis-condition-index-v1`。每个假设内部按条件 ID 排序后生成零起始序号，提示与查表共用同一顺序，避免 JSON 键重排改变索引含义。旧 `condition_id` 输入继续校验；双输入不一致仍拒绝。未提供索引时序列化不增加新字段，保留旧哈希。额外核对并同步了前端 DTO 与 Reader 详情入口，确保索引 `0` 的条件不会被隐藏；已重建随包 SPA。
- 阶段 4：新 V8 身份冻结 `structured_output_policy=provider-schema-or-json-v1`。SIWC/OpenAI 使用 strict schema，现有 DeepSeek Chat Completions 路由使用 `json_object`；未接入的供应商显式记录 `none`，不冒称受 schema 约束。原 Pydantic、数字、证据与范围校验保持权威。相同枚举通过共享定义去重，277 个证据候选的综合 schema 离线验证通过。

用户授权的 **1 次** `gpt-6.1-terra` SIWC 最小探测返回 HTTP 200，schema 随机枚举匹配；只记录状态，不保存凭证或模型原文。探测命令为 `python -m scripts.probe_chatgpt_structured_output --execute`，不加 `--execute` 时只预览且不访问凭证、不发请求。本次授权不包含第二次探测或完整研究。完整真实研究、报告质量与完整性仍待另行授权验收，不能由最小探测或离线测试推断。

严格结构化输出约束的是供应商接受的 schema 下完整、非拒绝输出的结构；拒绝、截断、证据范围错误和语义错误仍可能失败。当前 OpenAI 官方说明区分通用模型与微调模型的约束支持；本适配层保守地把字符串长度约束放回本地校验，并检查 schema 规模。参考：[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)、[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。

最终验证范围：32 个受影响 Python 测试文件共 **581 passed**；主会话复查修正诊断位置映射后，相关 **61 passed** 定向复验（与前述覆盖重叠，不累加）；另 **10 passed** 前后端契约检查。前端 4 个定向测试文件 **44 passed**，TypeScript/Vite 构建成功并同步生成 SPA。变更 Python 文件 Ruff、179 个 Markdown 文档检查、`git diff --check` 均通过。测试保留既有 Starlette 弃用与 MiMo 模型目录提示，构建保留包体积提示。本轮未执行全仓测试、完整真实研究或生产服务重启，也未提交/推送。独立审查代理因账户额度限制未完成，实际进行了主会话差异复查，不将其表述为独立审查通过。


## 8. 授权真实研究验收（2026-10-28）

运行：`run_20261028T062613775477Z_419b76bb`；对象：`002130.SZ`；专项/挑战与综合均选 `chatgpt / gpt-6.1-terra`。通过真实浏览器在 `127.0.0.1:8766` 提交一轮研究，使用独立临时 run store，原 `8767` 服务保持运行。

### 已验证与未通过项

- 执行终态 `completed`、Reader `ready`，但报告为 `partial / LOW_CONFIDENCE / specialist_summary`，总体评级为空。最终记录含 300 条事实、163 项来源、6 条假设、0 条有效挑战。事件与市场专项有效；经营与挑战失败，三个回应阶段跳过。
- 8 次原生研究请求均携带 `json_schema` 策略并有返回用量记录，未记录供应商请求失败；其中包括经营、事件、市场、挑战及事件复核。综合阶段未发出模型请求。不能据此宣称所有阶段和最终报告验收通过。
- 经营主请求与修正均在 `hypotheses[*].supporting_fact_ids` 处失败，代码为 `numeric_proposal_schema`。现有安全诊断只有位置，无法从已保存资料确定是数量上下限还是其他具体校验类别，不能猜测或放宽约束。
- 挑战主请求报 `challenge_schema_invalid` 与 `challenge_requirement_invalid`，修正后仍有 `challenge_requirement_invalid`。未记录 `challenge_condition_reference`，但因未形成有效挑战，条件索引方案的完整挑战闭环仍未实测通过。
- 白话解释终态 `partial`：137/257 段已解释，120 段保留原文、0 段待处理，原因 `stream_incomplete`。未点击重试。保存记录的数值/依据凭证离线回放通过。

### 确定的实现遗漏及修正

综合请求在本地 schema 适配时被 `unsupported_structured_schema_union` 拒绝，故没有 `native.structured_output.synthesis` 请求记录，也没有综合模型用量。离线使用本次保存的综合上下文复现：`reference_schema()` 生成的四个维度 `oneOf` 以必填 `dimension` 的不同 `const` 保证互斥，但没有 Pydantic 的 `discriminator` 元数据；原适配器只识别后者。此前只测基础 stage schema，遗漏了动态综合请求 schema。

适配器现也识别“同一必填字段在各分支中具有互不相同的常量”的互斥分支，等价转换为 `anyOf`；重叠分支仍拒绝。已为完整综合与定向修正两种真实 schema 构造链补回归，并保留重叠分支拒绝测试。相关 51 项离线回归通过；用本次保存输入重建综合提示成功（521853 字符），没有再次访问模型。该修复不能倒推本次报告已获得综合结论，也尚未完成修复后的真实验收。

只进行了这一轮授权研究。未改写已发布报告，未重跑研究或解释，未提交/推送。验收快照与安全诊断在 `/private/tmp/tradingagents-structured-live-20261028/acceptance-result.json`；完整报告保存在该目录独立 runs store 中。后续如需超出字段位置的安全校验类别/数量诊断或追加真实模型调用，应先确认范围。
