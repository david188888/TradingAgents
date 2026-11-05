# 数据能力目录与受控补证 — 实现计划

> **For agentic workers:** Implement task-by-task. 保留当前工作区其他未提交修改；没有 Git 发布授权前不 commit/push/PR。真实模型调用须另获授权。

**Goal:** 让 V9 专项在显式缺口处按短能力目录受控调用结构化补证工具，替代“几乎只会网页 `search_requests`”，同时保留证据门、专项隔离与非 Bull/Bear 研究目标。

**Architecture:**
- `dataflows/` 拥有能力目录定义、压缩视图、各卡后端适配与资格化入口。
- `execution/` 拥有 Gateway 调度、预算扣减、与 `insight_research` 补证环衔接。
- `agents/schemas/_insight.py` 扩展提交契约；`graph/insight_research.py` 消费结构化请求。
- Wind 走现有 `wind_provider` 适配器；无凭证则卡不可见。V9 预取链仍不自动派发 Wind。

**Tech Stack:** Python/Pydantic、现有 durable journal / BudgetLedger、pytest、现有 search coordinator。

**Spec:** [数据能力目录与受控补证工具层](../superpowers/specs/2026-11-05-capability-catalog-controlled-supplement-design.md)

Status: Tasks 1–5 offline complete; Task 6 (live run) needs explicit authorization. Task 5 decision: capability supplement stays always-on, so no `default_config` enable/per-role-limit key was added; per-role limit is code-frozen and the audit reading path is documented (design §13.1). Task 3 was later extended with consensus_eps, longhubang and holder_change (design §13.2).

## 设计 §12 关闭结论（对照当前代码）

1. **请求挂载点**
   在 `InsightSubmission` 增加 `capability_requests`（结构化）；保留 `search_requests` 一期兼容，宿主将其映射为 `news_search` 请求。Challenge / Response / Synthesis schema **不加**该字段。

2. **预算分账**
   复用已有桶，不新发明平行宇宙：
   - 网页双路：`DEEPSEEK_SEARCH` / `TAVILY_SEARCH` / `SEARCH_PAGE` / `SEARCH_ROUNDS` / `SEARCH_REVIEW`（现行 search policy 启用时写入 limits）。
   - 结构化补证次数：`SUPPLEMENT_CAPABILITIES`（默认 3 / run）+ `SUPPLEMENT_ROUNDS`（默认 1）。
   - 专项模型补写：仍走 `SEARCH_REVIEW`（`supplement_*` phase）或与实现时现行逻辑一致的模型桶；**不得**默默扩大 `DEFAULT_LIMITS` 总模型预算，除非用户另批。
   v1 产品语义对齐设计：每专项补证派发 ≤2 次能力调用，且受 `SUPPLEMENT_CAPABILITIES` 总上限约束；轮次默认保持 1，第二轮仅在配置显式提高 `SUPPLEMENT_ROUNDS` 后开启。

3. **Wind**
   使用 `tradingagents/dataflows/wind_provider.py`（CLI 封装）作为 `wind_enrich` 后端之一；凭证/CLI 缺失 → `requires` 失败 → 目录隐藏该卡。不在 graph 内直调 MCP，不把 Wind 接入最小预取默认集（与 `docs/integrations/wind.md` 一致）。

## Global Constraints

- 不恢复 Bull/Bear；挑战/综合阶段不开放写工具。
- 工具失败 / 空结果 → typed gap，不得写成方向性事实。
- 专项互不读草稿；补证回灌只用本角色可消费视图。
- 保留工作区其他未提交改动；本主题改动可独立提交。
- 使用 conda 环境 `tradingagents`；按 CONTRIBUTING 做 scoped 验证；无授权不做 live LLM。
- 防过度防御与提前抽象：Gateway 先支持 4 张高频卡，其余卡可先“目录可见 + 未实现 → unavailable”。

## Review Focus

- 模型传未知 `capability_id` / 跨角色卡 / 无 `gap_reason` 仍被执行。
- `search_requests` 兼容映射重复计费或绕过 `SUPPLEMENT_CAPABILITIES`。
- 补证增量泄露到其他专项 catalog。
- 无 Wind 时 `wind_enrich` 仍出现在 prompt。
- 挑战阶段 schema 或 prompt 误开工具。
- resume 后能力集 digest 变化却静默继续。

---

## Task 1: 能力卡 schema、目录加载与压缩视图

**Files:**
- Create: `tradingagents/dataflows/capability_catalog.py`
- Create: `tradingagents/dataflows/capability_catalog_data.py`（或同目录 yaml + loader；优先 Python 常量以免运行时文件 IO 争议——实现时二选一，测试夹具覆盖）
- Create: `tests/test_capability_catalog.py`
- Modify if needed: `docs/operations/a-share-data-capabilities.md`（仅增加“模型可见目录”导航句，不复制大表）

**Interfaces:**
- `CapabilityCard`（完整卡）
- `load_capability_catalog(*, role: str | None, available_requirements: set[str]) -> tuple[CapabilityCard, ...]`
- `compact_capability_cards(cards) -> list[dict]`（模型字段：id/title/solves/not_for/inputs/cost）
- `CATALOG_SCHEMA_VERSION = "capability-catalog-v1"`
- `catalog_identity_digest(cards) -> str`

**Steps:**
1. 先写测试：角色过滤、`requires` 隐藏、`prefetch_only` 不可请求、压缩卡不含 backends、digest 稳定。
2. 录入设计中的 ~12 张卡；`news_search` / `disclosure_search` / `shareholder_count` / `ir_qa` 标为 v1 implementable，其余可 `implemented=False`。
3. 跑 `pytest -q tests/test_capability_catalog.py`；Ruff 改动文件。

**Done when:** 测试通过；压缩卡适合塞进 prompt（单卡短文本）。 ✅

---

## Task 2: 提交契约 — `capability_requests`

**Files:**
- Modify: `tradingagents/agents/schemas/_insight.py`
- Modify: `tests/test_insight_protocol.py`（或新增 `tests/test_capability_requests_schema.py`）
- Modify: `tradingagents/execution/insight_model.py`（prompt 文案：`search_requests_allowed` 旁增加 capability 说明；schema 自动跟模型）

**Interfaces:**
```python
class CapabilityRequest(BaseModel):
    capability_id: str
    args: dict[str, object] = {}
    gap_reason: str

class InsightSubmission(...):
    insights: tuple[InsightProposal, ...]
    search_requests: tuple[str, ...] = ()
    capability_requests: tuple[CapabilityRequest, ...] = ()
```

**Steps:**
1. 先写测试：合法请求；空 gap_reason 拒绝；extra 字段 forbid；Review/Synthesis 模型无此字段。
2. 实现 schema；`insight_model` 仅在 `search_requests_allowed` 真时鼓励非空 capability/search 请求，否则提示必须空列表。
3. 跑相关 pytest + Ruff。

**Done when:** strict schema 含新字段；旧只含 `search_requests` 的 payload 仍可校验（默认空 tuple）。 ✅

---

## Task 3: Tool Gateway（先 4 张高频卡）

**Files:**
- Create: `tradingagents/execution/capability_gateway.py`
- Create: `tests/test_capability_gateway.py`
- Modify as needed: `tradingagents/execution/budget.py`（若需按卡 reserve 的 helper；优先复用 `DATA_CAPABILITY_CALLS` + `SUPPLEMENT_CAPABILITIES`，避免新桶）
- Adapters（薄包装，调用现有模块，不重写供应商）:
  - `news_search` → 现有 insight/search coordinator 路径
  - `disclosure_search` → 现有 CNINFO / official disclosure 能力
  - `shareholder_count` → a-stock-data / 现有 specialty 路径（选一个已存在可靠入口）
  - `ir_qa` → 互动易 / e 互动现有入口
  - 其余 id → 统一 `CapabilityUnavailable("not_implemented")`

**Interfaces:**
- `execute_capability_requests(requests, *, role, run_context, ledger) -> GatewayResult`
- `GatewayResult`: 合格增量材料句柄、gaps、executed ids、rejected reasons
- 单次入口内：校验 id∈角色可见且 implemented → reserve 预算 → 调适配 → 资格化 → 返回

**Steps:**
1. 先写测试：越权卡拒绝；无 gap_reason 拒绝；预算耗尽；not_implemented；成功路径用 stub 后端。
2. 实现 Gateway；**禁止** graph 直接 import 供应商 SDK。
3. Wind：`wind_enrich` 若调用则走 `wind_provider`；缺 CLI/凭证 → unavailable（Task 1 已隐藏更佳，Gateway 再兜底）。
4. 跑 pytest + Ruff。

**Done when:** 3 张结构化卡可测（news_search 走原搜索路径）；其他卡安全失败；审计字段可写入 journal。 ✅

---

## Task 4: 接入 `insight_research` 补证环

**Files:**
- Modify: `tradingagents/graph/insight_research.py`
- Modify: `tradingagents/execution/native_runner.py`（注入 gateway / 扩展 `supplement_insights`）
- Modify: `tradingagents/execution/insight_search.py`（若 `news_search` 复用；避免双实现）
- Tests: `tests/test_insight_research_capabilities.py`（或扩展现有 insight graph 测试）

**Behavior:**
1. 解析专项 raw 中的 `capability_requests`；校验后写入 `insight.capability_requests.{role}[.supplement_k]`。
2. 兼容：`search_requests` → 合成 `CapabilityRequest(capability_id="news_search", args={"query": q}, gap_reason="legacy_search_request")`，计入同一补证预算。
3. 每轮：合并待执行请求 → Gateway → 更新受影响角色 catalogs → 既有 `supplement_*` 模型复核逻辑。
4. 上下文增加 `capability_catalog: compact_capability_cards(...)`；`search_requests_allowed` 仍控制是否允许非空请求。
5. challenge / synthesis / focus 上下文不放可写目录（或放只读说明且 schema 无字段）。
6. identity 增加 `capability_catalog_version` + digest；变更 → `ResearchCheckpointConflict`。

**Steps:**
1. 先写失败测试：请求被执行并回灌；跨专项不泄露；挑战阶段无执行；resume digest 冲突；legacy search_requests 仍工作。
2. 接线；保持现有三轮网页 pending 队列语义可运行，但结构化请求优先走 Gateway。
3. 跑 scoped pytest；Ruff。

**Done when:** 专项缺口可触发结构化卡并修订 Insight；无授权 live 模型下用 stub caller 覆盖。 ✅

---

## Task 5: 配置、文档与测量钩子

**Files:**
- Modify: `tradingagents/default_config.py`（显式补证相关键的注释与默认：目录启用、每专项上限；不悄悄加大模型总预算）
- Modify: `ARCHITECTURE.md`（Owners 表增加 capability catalog / gateway 一行）
- Modify: `docs/operations/evidence-research.md`（补证从 search_requests 扩展到 capability_requests 的操作说明）
- Optional: 只读测量脚本或测试，统计 prompt 中 catalog 大小 vs 旧 search-only（无生产行为变更）

**Steps:**
1. 文档与配置同主题提交。
2. `git diff --check`；确认未卷入无关未提交文件。
3. 按 CONTRIBUTING 跑本主题相关测试；前端若未改则不强制 build。

**Done when:** 当前态文档指向新契约；操作者知道如何读审计里的 capability 调用。 ✅

---

## Task 6:（可选，需另授权）一次真实 run 对照

**Only with explicit user authorization for live providers.**

1. 选一只 A 股，跑 V9；记录 `insight.model_usage`、capability 审计、补证次数。
2. 对照改前 run（若有）看 search 次数与输入体量，不在无数据时写百分比承诺。
3. 结论写短 review 备忘；不自动改默认预算。

---

## 建议提交切分

1. Task 1–2：目录 + schema（可先合）
2. Task 3：Gateway + 4 卡
3. Task 4：insight 接线
4. Task 5：文档/配置

每片保留无关 dirty 文件不动。

## 实现时不要做

- 把 87 个 a-stock 端点暴露给模型
- 在 challenge 为“辩赢”取数
- 扩大默认模型总尝试次数充当补证预算
- 删除 `search_requests` 字段（先兼容）
- 未授权 live LLM / 未授权 git 发布
