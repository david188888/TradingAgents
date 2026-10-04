# T05 隐含 LLM 调用审计

Status: Historical

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

- **范围**：静态代码审计 + 对 25 个既有 run 事件日志的只读统计。**未发起任何 LLM 调用或新研究运行。**
- 目的：为设计 §5.5 的预算计数器提供真实调用点清单，回答「哪些调用会绕过预算」。
- 行号对应代码基线 `a6a3f4c60f678c230a6290ed25c13a8da7a1431c`（合回后需重跑 `grep -n` 校准）。

## 0. 结论摘要

| 问题 | 实测结论 |
| --- | --- |
| Evidence Steward 内部有多少模型调用？ | **1 个节点内最多 3 类独立调用路径**（advisor / layer1 / layer2）+ 聚类 1 次，**全部带副作用且都在预算体系之外** |
| SDK 自带 retry 是否纳入预算？ | **否**。`max_retries` 透传给 SDK，SDK 内部重试**不产生 `model.started` 事件** |
| source fallback 链是否会放大 HTTP 次数？ | **会，且不受用户选择约束** —— 冷却状态会**隐式**追加 fallback vendor |
| rate limit 语义 | 已有 `VendorRateLimitError` / `RateLimitError` 分类，但**没有全局信号量**，与设计 §5.4 要求不符 |
| 现有事件能否支撑预算？ | **部分能**。已有 `attempt_id` / `model_call_id` / `turn_id` / `graph_task_id` 四级标识，可直接复用 |

## 1. 全部 LLM 调用点（file:line）

### 1.1 角色路径（`invocation_path="role"`）

设计 §5.5 预算「主分析模型调用 正常路径 5 次 = 3 专项 + 1 反证 + 1 综合」。当前 classic 的角色调用点：

| # | file:line | 调用者 | 说明 |
| --- | --- | --- | --- |
| R1 | `tradingagents/agents/analysts/market_analyst.py:127` | `chain.invoke(state["messages"])` | 市场分析师 |
| R2 | `tradingagents/agents/analysts/news_analyst.py:118` | `chain.invoke(state["messages"])` | 新闻分析师 |
| R3 | `tradingagents/agents/analysts/fundamentals_analyst.py:81` | `chain.invoke(state["messages"])` | 基本面分析师 |
| R4 | `tradingagents/agents/researchers/bull_researcher.py:153` | `llm.invoke(prompt)` | 多头研究员 |
| R5 | `tradingagents/agents/researchers/bear_researcher.py:145` | `llm.invoke(prompt)` | 空头研究员 |
| R6 | `tradingagents/agents/managers/research_manager.py:330` | `structured_llm.invoke(one_prompt)` | 研究经理结构化路径 |
| R7 | `tradingagents/agents/managers/research_manager.py:358` | `llm.invoke(one_prompt)` | 研究经理自由文本回退 |
| R8 | `tradingagents/agents/managers/research_manager.py:428` | `structured_llm.invoke(one_prompt)` | 第二段结构化 |
| R9 | `tradingagents/agents/managers/research_manager.py:438` | `llm.invoke(one_prompt)` | 第二段自由文本回退 |
| R10 | `tradingagents/agents/managers/research_manager.py:494` | `structured_llm.invoke(prompt)` | 计划生成 |
| R11 | `tradingagents/graph/setup.py:72` | `llm.invoke(...)` | graph 内直接调用 |
| R12 | `tradingagents/agents/analysts/sentiment_analyst.py:116` | `invocation_path="sentiment.prefetch.stocktwits"` | 情绪预取 |
| R13 | `tradingagents/agents/analysts/sentiment_analyst.py:126` | `invocation_path="sentiment.prefetch.reddit"` | 情绪预取 |

### 1.2 ⚠️ 隐含调用点（不在角色图内，**绕过设计 §5.5 的 5 次主分析预算**）

| # | file:line | `invocation_path` | 调用者 | 绕过预算？ |
| --- | --- | --- | --- | --- |
| **H1** | `tradingagents/dataflows/consistency.py:111` | `consistency.clustering` | `_cluster_via_llm` | **是** —— 语义聚类，设计 §5.5 明确「若复用也计入」 |
| **H2** | `tradingagents/dataflows/news_advisor.py:311` | `evidence.news_advisor` | `_analyze_via_llm` | **是** —— 覆盖缺口分析 + 可能触发补充检索 |
| **H3** | `tradingagents/dataflows/news_advisor.py:159` | `evidence.news_layer1_sentiment` | `_run_layer1_sentiment` | **是**（默认关闭） |
| **H4** | `tradingagents/dataflows/news_advisor.py:209` | `evidence.news_layer2_review` | `_attach_layer2_conclusion` | **是**（默认关闭） |

**H2 的放大效应**：`analyze_news_coverage`（`news_advisor.py:57`）返回的 `should_enrich=True` 会**触发新一轮供应商检索**。即：**1 次 LLM 调用 → 追加 N 次 HTTP 取数**。这是设计 §5.5「冻结前至多一轮、3 个能力」最可能被突破的路径。

**H3/H4 默认关闭**（`news_layer1_enabled` / `news_layer2_enabled` 实测为 `true`，见 T01 §4）。**注意：这两个开关在既有 run 的 `effective_config` 中确实为 `true`**，因此 H3/H4 **可能已经发生**。

### 1.3 结构化输出修复路径（设计 §5.5「结构化输出修复 全 run 最多 2 次」）

`tradingagents/agents/utils/structured.py`：

| file:line | 行为 | 预算影响 |
| --- | --- | --- |
| `:70-79` | `with_structured_output` 不可用 → 返回 `None`，降级为自由文本 | 一次性能力探测，非模型调用 |
| `:98` | `structured_llm.invoke(prompt)` 主路径 | 正常 |
| `:99-101` | 返回 `None` → 抛 `ValueError` | **修复触发** |
| `:106-110` | 捕获任意 `Exception` → warning → 继续 | **修复触发** |
| `:113` | `plain_llm.invoke(prompt)` 自由文本回退 | **第二次模型调用** |

**问题**：`structured.py:98` 与 `:113` 是**两次独立模型调用**，但代码里**没有计数器**。「修复次数」在当前实现中**不可观测**。

**另一处**：`tradingagents/web/debate_summary.py:284` 与 `:294` —— `structured_llm.invoke(prompt)` 失败后 `structured_llm.invoke(correction)`，这是**显式的第二次调用**（correction prompt），同样无计数。

### 1.4 Portfolio Manager —— 不是模型调用

设计 §3 已指出「Portfolio Manager 为确定性收尾，不调用传入的 llm」。**代码核实：无 `invoke` 调用点**。删除该节点**不构成模型成本优化** —— 设计的这个判断成立。

## 2. Retry 行为

### 2.1 SDK 自带 retry（**当前最大的预算漏洞**）

`tradingagents/llm_clients/provider_kwargs.py:71-75`：

```python
# SDK retry budget is cross-provider. Forward it only when explicitly set
max_retries = config.get("llm_max_retries")
if max_retries is not None and max_retries != "":
    kwargs["max_retries"] = _coerce_max_retries(max_retries)
```

`max_retries` 被透传给 4 个 provider client 的 SDK：

| file:line | client |
| --- | --- |
| `tradingagents/llm_clients/openai_client.py:228` | OpenAI 兼容 |
| `tradingagents/llm_clients/anthropic_client.py:11` | Anthropic |
| `tradingagents/llm_clients/azure_client.py:9` | Azure |
| `tradingagents/llm_clients/google_client.py:34` | Google |

**⚠️ 关键实测结论**：SDK 内部重试**发生在 `llm.invoke()` 调用之内**，**不产生 `model.started` / `model.completed` 事件**。证据：

```
attempts-per-call distribution: {309: 1}
total model.started events: 309
```

15 个 completed run 共 309 次模型调用，**每一次都只有 1 个 `model.started`、恰好 1 个 `model.completed`**，`retried_call_ids = 0`（全部 15 个 run）。

但其中一个 run 在**失败后**留下 13 次 started/13 次 completed：

| run | status | started | completed | token |
| --- | --- | ---: | ---: | ---: |
| `run_20260827T155953563764Z_9d17e0a4` | **failed** | 13 | 13 | **419,932** |

**推论**：若 `llm_max_retries` 生效，SDK 会在**单次 `invoke` 内**重试 N 次而事件流只记 1 次。**这 13 次调用的实际尝试次数无法从事件日志恢复 → 计为 `unknown`，不能记 1。**

**实测配置**：`effective_config` 中**未见 `llm_max_retries` 键**（T01 §4 已列全量键，无此项）。`default_config.py:21` 声明了 `TRADINGAGENTS_LLM_MAX_RETRIES` → `llm_max_retries` 映射，但**这些 run 未设置该环境变量**，因此 `max_retries` 走 SDK 默认值（OpenAI SDK 默认 `max_retries=2`）。

> **⚠️ 该默认值本轮 `unknown` —— 未读取任何 provider 客户端的运行时配置，不排除 SDK 版本差异。** 需在 T23 由 E agent 实测确认。

**对设计的直接结论**：设计 §5.5「SDK 自带 retry 必须纳入或关闭，不能绕开总预算」——**当前未满足**。新 profile 必须显式设 `max_retries=0` 或把 SDK 重试计入 `attempt_id`。

### 2.2 应用层重试

`model.started` 事件的 `attempt_id` 字段（形如 `attempt_44a379c94f0843148c5ea9a3c14fddf2`）**已经存在**，说明观测层已预留 attempt 概念。实测 15 个 completed run 中每次调用的 attempt 唯一，**无应用层重试被触发**。

## 3. Source fallback 链

### 3.1 链长度（`tradingagents/dataflows/registry.py:334` 的 `VENDOR_METHODS`，实测 61 个 method / 23 个 vendor）

| method | fallback 顺序（按注册序） | 链长 |
| --- | --- | ---: |
| `get_stock_data` | mootdx → tushare → alpha_vantage → yfinance | 4 |
| `get_adjusted_price_history` | wind → tushare → akshare → yfinance → alpha_vantage | **5** |
| `get_news` | tavily → doubao → bocha → eastmoney → alpha_vantage → yfinance → china_exchange | **7** |
| `get_global_news` | tavily → doubao → bocha → yfinance → alpha_vantage | 5 |
| `get_fundamentals` | tushare → akshare → alpha_vantage → yfinance | 4 |
| `get_income_statement` / `get_balance_sheet` / `get_cashflow` | tushare → sina → alpha_vantage → yfinance | 4 |
| `get_a_share_valuation` | tencent | 1 |
| `get_a_share_cninfo_announcements` | cninfo → china_exchange | 2 |

**设计 §5.5 预算：「数据取数 最多 24 个逻辑 capability 调用、64 个 HTTP 尝试」。**

**⚠️ 放大风险**：单个 `get_news` 失败会尝试 **7 个** vendor。24 个逻辑调用在**全链失败**情形下可放大到远超 64 次 HTTP。**「逻辑调用」与「HTTP 尝试」必须分别计数，否则 64 次上限形同虚设。**

### 3.2 ⚠️ 隐式 fallback 突破用户显式选择

`tradingagents/dataflows/interface.py:271-276`：

```python
# A stored cooldown only represents a prior transient failure. It
# gets the same implicit safety-net fallback as a live 429/network
# failure, even when the user explicitly selected one primary.
for extra in VENDOR_METHODS[method]:
    if extra not in fallback_vendors:
        fallback_vendors.append(extra)
        implicit_fallback_triggered = True
```

**这是对设计 §8.5「不因一个源失败强制更换用户显式选定的供应商策略」的直接违反** —— 代码注释自己声明了这一点：即使用户**显式选定单一 vendor**，处于冷却状态时仍会**隐式追加整条 fallback 链**。

对新 catalyst profile 的影响：若不处理，`raw` 与 `qfq` 的「不混拼」要求（设计 §8.5、§13.5）会在 fallback 时被破坏 —— **T13 必须为此加断言**。

### 3.3 已实测的 fallback 后果

8/15 completed run 的 `degraded_data_sources` 记录：

```json
{"capability": "search_macro_series", "status": "unavailable",
 "reasons": [{"code": "vendor_error", "vendor": "wind"}],
 "attempted_vendors": ["wind"], "selected_vendors": []}
```

`attempted_vendors: ["wind"]` 而 `selected_vendors: []` —— **尝试了但没有任何成功源**。这类必须记为 `unavailable`，**不得写成「无事件」**（设计 §8.4、T18）。

## 4. Rate limit 语义

### 4.1 已有的错误分类（可复用）

| 类型 | 定义位置 |
| --- | --- |
| `VendorRateLimitError` | `tradingagents/dataflows/wind_provider.py:42`（基类），`:104` `WindRateLimitError` |
| Wind 错误码映射 | `wind_provider.py:618` `RATE_LIMIT_ERROR`、`:619` `CONCURRENCY_LIMIT_ERROR`、`:638` `"429"` |
| `RateLimitError` | `tradingagents/dataflows/errors.py`，`eastmoney.py:107-109` 抛出于 HTTP 429 |
| provenance 归类 | `tradingagents/observability/provenance.py:429-430` → `"rate_limited"` |
| web 层 reason code | `tradingagents/web/manager.py:1651` → `"vendor_rate_limit"` |
| 东财/豆包/Bocha 冷却 | `eastmoney.py:107`、`doubao_news.py:299-300`、`bocha_news.py:358-359` → `RATE_LIMIT_COOLDOWN_SECONDS` |

**评价**：rate limit 的**检测与分类**已经比较完整，可直接复用。

### 4.2 缺失的部分

| 设计要求 | 现状 |
| --- | --- |
| 「必须使用全局 LLM/数据源信号量」（§5.4） | **无全局信号量**。`TRADINGAGENTS_WIND_MAX_CONCURRENCY` 仅限 Wind 单 vendor |
| 「不能让 batch 并发数乘以角色并发数无限放大」（§5.4） | `analyst_concurrency_limit` 实测为 `1`，**串行**，暂无放大。但新 profile 要开 2 时必须先有全局信号量 |
| 「预算检查发生在每次调用之前并预留额度；并发原子扣减」（§5.5） | **无预算账本**。15 个 run 中 `budget` / `usage` / `cost` 文件数为 **0** |
| 「auth 错误不重试绕过权限」（§5.5） | **未验证** —— 未找到 auth 错误与普通错误的 retry 区分逻辑 |

## 5. ⚠️ policy 版本硬约束（复核）

```text
tradingagents/research/horizon_policy.py:23
    POLICY_VERSION = "horizon-policy-v2"

tradingagents/runtime/contracts.py:8
    RuntimePolicyVersion = Literal["horizon-policy-v2", "horizon-policy-v3"]
```

**`horizon-policy-v3` 是已激活的测试门控策略。** `RuntimePolicyVersion` 的实际消费点比任务计划 §3 所写更多：

| 文件 | 处数 |
| --- | --- |
| `tradingagents/runtime/reconciliation.py` | **15**（`:24, 74, 118, 255, 336, 483, 545, 688, 730, 794, 836, 867, 915` 等） |
| `tradingagents/web/manager.py` | 2（`:41, 1536`） |
| `tradingagents/runtime/fingerprint.py` | 已 import |
| `tradingagents/execution/runner.py` | 已 import |
| `tradingagents/observability/canonical.py` | 已 import |

→ **`catalyst-evidence-policy-v1` 禁止加入该 Literal。** 新 policy 必须走独立模块与独立字段。理由不只是命名相近：该 Literal 已被 20 处签名与默认值绑定，加入新值会同时改变 horizon 门控的运行时契约与恢复指纹语义。

## 6. 预算计数器方案建议

### 6.1 可直接复用的现有资产

事件流**已经**提供设计 §5.5 要求的账本键 `run_id + logical_call_id + attempt_id` 的前两级：

| 现有字段 | 位置 | 复用为 |
| --- | --- | --- |
| `model_call_id` | `events.jsonl` `model.started/completed.payload` | `logical_call_id`（一个逻辑调用 = 一次 invoke） |
| `attempt_id` | 同上 | `attempt_id`（一次实际尝试） |
| `turn_id` | 同上 | 角色轮次 |
| `graph_task_id` | 同上 | 图任务 |
| `invocation_path` | 同上 | **分类键**：`role` / `direct:*` 直接映射设计 §5.5 的预算桶 |
| `usage.total_tokens` 等 | `model.completed.payload.usage` | token 账本 |
| `duration_ms` | `model.completed.payload` | 阶段耗时 |
| `vendor_call_id` | `data.progress` 事件 | HTTP 尝试计数 |
| `fallback_chain` | `provenance.start_attempt(...)` | fallback 顺序审计 |

**结论：不需要新建账本存储。** 缺的是**计数器**与**持久化的扣减记录**。

### 6.2 建议方案

**(1) 预算桶映射**（按 `invocation_path` 分类，零新增字段）：

| 桶 | 匹配 | 设计 §5.5 上限 |
| --- | --- | --- |
| `main_analysis` | `invocation_path == "role"` 且新 profile 的三个专项/反证/综合 | 5 |
| `semantic_preprocess` | `direct:consistency.clustering`、`direct:evidence.news_advisor`、`direct:evidence.news_layer*` | 2 |
| `structured_repair` | `structured.py:113` 回退 + `debate_summary.py:294` correction | 全 run 2 / 每阶段 1 |
| `network_retry` | `attempt_id` 递增且 `model_call_id` 不变 | 全 run 3 |
| `total_attempts` | 全部 | **12** |
| `data_http` | `vendor_call_id` 计数（**与逻辑调用分开**） | 64 |

**(2) 必须在代码层做的 4 件事**：

1. **关闭 SDK retry**：新 profile 显式 `max_retries=0`；或在 client 层包一层，把 SDK 内部重试映射为新的 `attempt_id`。**不做这一条，「全 run 最多 12 次」就是假的。**
2. **在 `invoke` 之前原子扣减**：`llm.invoke()` 是唯一的收敛点。在 `observer.py:680` 的 `direct_call_scope` 与 role 路径上各加一个 `budget.reserve(bucket, logical_call_id)`，返回 `False` 时**不发起调用**。
3. **修正 token 缺失语义**：`model.completed` 无 `usage` 键时写 `unknown`；`model.started` 无配对 `model.completed` 时写 `unknown` 并**保守计为已消耗**（设计 §5.5）。实测已有 5 个这样的 run。
4. **把 `should_enrich` 纳入数据预算**：H2 返回 `should_enrich=True` 触发的补充检索，必须消耗**同一个 run 预算**（设计 §5.1「冻结前至多一轮、3 个能力」）。

**(3) 恢复语义**（设计 §5.5「恢复同一 run 必须继承所有已消耗额度，不能从 0 重置」）：账本按 `run_id` 持久化，恢复时**读取已消耗额度**而非重置。`checkpoint_enabled` 在既有 run 中为 `false`，因此**恢复路径本轮未被验证**。

## 7. 验收自查

- [x] 每个隐含 LLM 调用点有 file:line —— §1，共 13 个角色 + 4 个 `direct:*`
- [x] retry 行为 —— §2（SDK retry **未纳入**，附 309/309 实测证据）
- [x] fallback 顺序 —— §3.1（61 method / 23 vendor 链长表）
- [x] 每项标注是否绕过设计 §5.5 预算 —— §1.2 表格「绕过预算」列
- [x] 预算计数器方案建议 —— §6
- [x] `horizon-policy-v3` 陷阱已记录 —— §5
- [x] 无凭据、无 token 值、无带凭据 URL
- [x] 未把 `unknown` 记为 0 或 1（SDK 默认 `max_retries` 标 `unknown`）
