# DeepSeek／Tavily 双路检索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为新 Web 公司研究接入双路初始检索、专用接口数据回退和最多三轮研究中补证，形成可计算、可追溯且有硬预算的研究输入。

**Architecture:** 专用接口继续负责标准化基础数据；独立检索协调器经持久预算调用 DeepSeek／Tavily。准入后的材料追加证据版本，只有相关专项复核，最终综合读取有效版本。新工作流和记录显式分支，旧 V1／V7 保留原解析、执行和恢复规则。

**Tech Stack:** Python／Pydantic／requests、现有持久账本与本地 PDF 解析器、React 18／TypeScript、pytest／Vitest／Playwright。复用 Conda `tradingagents`，不新增运行依赖。

**Spec:** [已批准设计](../specs/2026-10-23-dual-search-research-design.md)。执行者必须先读设计及 root、`tradingagents/`、`frontend/` 的 `AGENTS.md`。

Status: Historical — 2026-10-24 已完成任务 1–11 的实现、离线验收及独立审查修复。
实施结果见[收尾记录](../../reviews/2026-10-24-dual-search-closeout.md)；现役行为见[双路搜索合同](../../contracts/dual-search-research.md)。
以下步骤、预期结果及未勾选清单保留制定时的写法，不代表当前开放待办。
**Do not use this document as evidence of current implementation behavior.**

## Global Constraints

- 每家公司、每次独立 run：DeepSeek Search 50 次、Tavily Search 50 次；全部 Agent／阶段／密钥共享各服务额度，失败、重试、未知派发均计数。
- 额外正文获取共 8 次 URL 尝试；直接下载重定向逐跳计数、最多两跳；研究中补搜最多 3 轮。
- 搜索相关活动累计 90 秒；默认整次研究活动时限仍为 300 秒；两路并发按活动区间并集计时，恢复不重置。
- 模型基础池 12、补证复核池 9、父池 21；复核每轮最多 3 次实际尝试，重试及修复计入本轮和复核池。
- 专用接口保留 24 次能力／64 次 HTTP 子池；新策略 HTTP 父池最多 172，搜索不能挤占旧子池或绕过父池。
- 默认 Tavily basic、关闭自动升级；查询规划、去重和停止不增设模型调用。无合格增量不调用复核；最多八个追加式快照。
- 新闻／行业／竞争主要双路搜索；身份／简介／量化数据优先专用接口；接口链失败或字段不足可由合格网页字段恢复并参与计算。
- 不将搜索摘要当原文、预测当实际、当前页面当历史版本；不以供应商 score 当研究置信度，不把转载计为独立信源。
- 生产选择 `evidence-production-v8`／`native-research-kernel-v7`，新增 `research-record-v2`；规划时已确认这三个标识未被代码使用。旧常量不改义。
- 不执行真实付费验收、服务重启、数据清理或 Git 发布；这类操作另遵循已有授权和项目边界。任务形成独立可审查提交边界，获 Git 发布授权后再提交／推送。

## Review Focus

1. 部分字段失败而接口整体成功：仅回退缺失字段，不重复搜索整个能力；Task 7 固定测试。
2. 两家返回同页不同参数、转载或截断内容：保留提取血缘及覆盖局限，不增加独立来源；Task 4／5 固定测试。
3. 第三个专项复核前发生重试：重试占用本轮第三次，不产生第四次调用，不宣称跳过专项已更新；Task 8 固定测试。
4. 搜索崩溃后恢复、并行请求晚到：预算及已终结轮次不重开，结果不得进入错误输入版本；Task 2／8 固定测试。
5. 最新证据改变数值但无关专项未重跑：旧输入仍可重放，受影响推断不可沿用旧收据，无关推断不失效；Task 6／9 固定测试。

---

## 文件与接口地图

新代码按职责拆开，不整体重构现有大文件。以下新类型均由 Task 1 定义，后续任务不得发明同义封装。

| 文件 | 职责 |
| --- | --- |
| `agents/schemas/_search.py` | `SearchRequestV1`、`SearchHitV1`、`SearchOutcomeV1`、`EvidenceGapV1`、`SearchBatchV1`、`SearchReviewV1`、`FieldRequirementV1`、`QualifiedFieldV1`、`AdmissionBatchV1` |
| `agents/schemas/_research_record_v2.py` | `ResearchRecordV2`、`EvidenceSnapshotV2`、复核、派生检查和替代关系 |
| `execution/search_budget.py` | 原子预算组合、活动时钟、恢复计量；使用现有持久账本 |
| `dataflows/deepseek_search.py`、`tavily_search.py`、`search_pages.py` | 纯 HTTP 适配、结构规范化、正文／URL 安全校验 |
| `execution/search_coordinator.py` | 查询编译、双路执行、缓存、去重、轮次批次结果 |
| `research/search_admission.py`、`search_recovery.py` | 原文观察准入、结构字段恢复与口径校验 |
| `research/evidence_revisions.py` | 追加与更正、字段／检查／数值重算和版本血缘 |
| `dataflows/search_sources.py` | 新采集器扩展：初始搜索和接口缺口回退 |
| `execution/search_reviews.py` | 三轮控制、专项复核调度、持久检查点 |

`ResearchRecord = ResearchRecordV1 | ResearchRecordV2` 及 `parse_research_record(value: Mapping[str, object]) -> ResearchRecord`
放在 `research/record_codec.py`。V1 不继承 V2 的新规则；V2 不通过放宽 V1 的 validator 实现。
公共 facade 继续导出旧名，同时导出新类型。新任务测试工厂统一在 `tests/search_fixtures.py`，
提供 `make_v2_record()`、`make_search_request()`、`make_gap()`、`make_search_harness()`；全部离线、合成数据，无凭证。

## Task 1: 闭合检索契约和多版本记录

**Files:** Create 上表两个 schema 文件、`research/record_codec.py`、`tests/search_fixtures.py`、`tests/test_search_contracts.py`；Modify `agents/schemas/__init__.py`。

**Interfaces:**
- `SearchRequestV1` 表达任务 ID、需求类型、公司身份、查询、日期范围、缺失字段需求和轮次；需求类型限定初始主题、数据恢复、研究补证。
- `EvidenceGapV1` 绑定缺口 ID、目标能力／假设／挑战、证据需求、优先级、时间和请求专项；不接受任意工具或 API 参数。
- `SearchHitV1` 保留服务、原始 URL、规范 URL、标题、摘要、可选正文、发布时间及供应商元数据；原文和摘要不可互换。
- `SearchOutcomeV1` 区分成功、空结果、不可用和明确错误代码；`SearchBatchV1` 绑定输入版本、任务、结果、停止原因和用量。
- `FieldRequirementV1` 保存所需身份、字段、期间、单位／币种／口径及窗口，不包含值；`QualifiedFieldV1` 保存匹配需求的值、原文定位及证据血缘，值和血缘不能为空。`AdmissionBatchV1` 返回观察、字段、拒绝和冲突。
- `SearchReviewV1` 保存角色、输入版本、原目标、维持／修正／撤回／无法判断、事实引用、新风险及下一轮缺口。
- `ResearchRecordV2` 的快照从 0 连续递增、最多八个，保留各阶段适用版本与不可变原条件。

- [ ] 写 `test_v1_roundtrip_unchanged`、`test_v2_eight_snapshots_and_tamper_rejection`、`test_gap_rejects_executable_tool_args`。断言旧记录逐字段往返一致；第九快照、错父哈希、删除父证据、未知版本均抛验证错误。
- [ ] 运行 `python -m pytest tests/test_search_contracts.py -q`，预期因新模块／行为未实现失败。
- [ ] 实现上述闭合类型、引用图和区分版本的 codec；字段长度沿用现有文本界限，查询在 Task 3 编译时另校验供应商限制。
- [ ] 重跑新测试及 `tests/agents/test_research_record.py`、`tests/test_native_record.py`，预期全部通过；检查差异形成契约提交边界。

## Task 2: 持久预算、父子池及活动时钟

**Files:** Create `execution/search_budget.py`、`tests/test_search_budget.py`；Modify `execution/budget.py`、`runtime/catalyst_checkpoint.py`、`execution/config_identity.py`、`research/native_versions.py`。

**Interfaces:** `SearchBudget(ledger, policy, clock)`；`reserve_search(provider: str, task_id: str) -> Reservation`、`reserve_page(task_id: str) -> Reservation`、
`reserve_review(round_id: str, role: str, attempt_id: str) -> Reservation`，不足抛现有 `BudgetExhausted`。
`activity_batch(batch_id)` 为上下文管理器；`remaining_seconds() -> float`。派发和结算沿用账本方法，组合预留原子完成。
新策略分别冻结基础／复核／父池及 HTTP 父池；旧身份继续使用原 limits。

- [ ] 写 `test_search_50_then_51_refused`、`test_pages_8_then_9_refused`、`test_model_pools_12_9_21`、`test_http_total_172_and_dedicated_64`；精确断言被拒绝请求未派发、换密钥不增加额度。
- [ ] 写 `test_concurrent_last_slot_atomic`、`test_resume_unknown_dispatch_consumed`、`test_parallel_activity_union_and_model_pause`：假时钟下并发区间不重复计时，模型阶段暂停搜索时钟，崩溃区间保守结算，剩余时间不回升。
- [ ] 运行 `python -m pytest tests/test_search_budget.py -q` 取得预期失败，再实现组合父子池、持久时钟及搜索任务与模型任务分类。
- [ ] 重跑新测试及 `tests/test_catalyst_budget.py`、`tests/test_native_retry.py`，预期通过且旧 12 次策略不变；检查差异形成预算提交边界。

## Task 3: 两家搜索与正文适配器

**Files:** Create `dataflows/deepseek_search.py`、`dataflows/tavily_search.py`、`dataflows/search_pages.py`、`tests/test_search_providers.py`、`tests/test_search_pages.py`；复用现有 `news_key_health.py` 的健康规则，不调用旧新闻路由。

**Interfaces:** 每家 `search(request: SearchRequestV1, *, session, budget: SearchBudget) -> SearchOutcomeV1`；
`fetch_page(url: str, *, provider: str, task_id: str, session, budget: SearchBudget) -> SearchOutcomeV1`。
适配器本身不做重试，协调器最多授权一次瞬态重试；每个 HTTP 派发前先预留。
DeepSeek 使用官方工具端点及现有 key；Tavily 使用既有多密钥配置，均独立于研究模型配置。

- [ ] 写 `test_deepseek_query_unicode_128_and_nullable_date`：128 字符可请求、129 拒绝；日期未知保持未知。断言 `count=8`、`need_content=true`，不发送模型参数。
- [ ] 写 `test_tavily_basic_no_auto_upgrade`、`test_provider_http_classification`、`test_no_credentials_no_dispatch`：默认 basic，401／402 无原样重试，429／5xx 返回可重试类别，空结果不当网络失败。
- [ ] 写 `test_page_redirect_private_target_rejected`、`test_redirect_hops_charge_same_8_pool`、`test_oversize_pdf_rejected`：每跳校验解析后地址，保留现有 20 MiB／500 页解析上限；正文一次一个 URL，不扩大批量额度。
- [ ] 运行两个新测试文件取得预期失败，实现 mock session 可覆盖的请求与响应适配；默认关闭 requests 隐式重试。
- [ ] 重跑新测试及 `tests/test_tavily_news.py`、`tests/test_news_provider_resilience.py`，预期通过；原新闻实现不变，形成适配器提交边界。

## Task 4: 双路协调、去重、缓存和停止

**Files:** Create `execution/search_coordinator.py`、`tests/test_search_coordinator.py`。

**Interfaces:** `SearchCoordinator(session, budget, journal)`；
`collect(requests: tuple[SearchRequestV1, ...], *, input_snapshot_id: str) -> SearchBatchV1`；
`compile_queries(gap: EvidenceGapV1) -> tuple[SearchRequestV1, ...]`。
每轮最多三个优先缺口，每缺口每服务最多两个区别查询；初始固定新闻／行业／竞争三个主题。
编译保留公司代码、时间和操作符，不通过盲目截断凑 128 字符；无法编译返回明确拒绝。

- [ ] 写 `test_initial_topics_paired`、`test_priority_top_three_and_query_cap`、`test_one_provider_unavailable_degrades`；断言单服务失败不清空另一家成功结果，也不调用第三家搜索服务。
- [ ] 写 `test_same_url_tracking_and_syndication_one_family`、`test_summary_never_becomes_body`、`test_completed_task_cached`、`test_unknown_dispatch_not_resent`；规范 URL 不抹去有意义的文档参数，保留原 URL 与转载关系。
- [ ] 写 `test_transient_retry_once_counts_budget`、`test_cancel_and_deadline_prevent_retry`；最多一个瞬态重试，缓存身份包括查询／服务／时间／深度。
- [ ] 运行 `python -m pytest tests/test_search_coordinator.py -q` 取得失败，随后实现双路执行、原始结果捕获、规范化与有序收集；使用现有全局数据槽，单 run 最多两路并行。
- [ ] 重跑 Task 2–4 测试，预期通过；检查去重和计费用量未知不记零，形成协调器提交边界。

## Task 5: 原文准入与量化字段恢复

**Files:** Create `research/search_admission.py`、`research/search_recovery.py`、`tests/test_search_admission.py`、`tests/test_search_recovery.py`；复用 `dataflows/disclosure_documents_v2.py` 与 `native_qualification.py` 的纯解析规则。

**Interfaces:** `admit_search_batch(batch: SearchBatchV1, *, ticker: str, cutoff: date) -> AdmissionBatchV1`；
`recover_fields(admitted: AdmissionBatchV1, *, requirements: tuple[FieldRequirementV1, ...]) -> AdmissionBatchV1`。
原文观察按确定性片段保存；模型不能把未知数字填为结构字段。每片段最多 4,000 字符，截断标记保留；用于计算的字段片段不得截断关键上下文。

- [ ] 写 `test_official_report_recovers_missing_revenue`：固定报告原文解析的数值与单位转换后可计算；保存真实网页来源，不能变成 `sina.*`。
- [ ] 写 `test_wrong_company_period_unit_and_forecast_rejected`、`test_missing_price_series_not_recovered_by_return_article`、`test_historical_page_vintage_unverified`；断言不合格材料可保留但对应能力仍缺失。
- [ ] 写 `test_provider_summary_has_no_original_quote`、`test_date_unknown_not_today`、`test_conflicting_fields_both_retained`、`test_clipped_table_not_calculable`；不以两个引擎相同摘要作为交叉验证。
- [ ] 运行两个新测试文件取得失败，实现有限已知结构的本地解析及身份／期间／单位／口径验证；不新增付费提取模型，未知布局明确不支持。
- [ ] 重跑新测试及 `tests/test_official_numeric_cells.py`、`tests/test_financial_detail_fields.py`，预期通过，形成准入提交边界。

## Task 6: 追加版本、重算与数值证明

**Files:** Create `research/evidence_revisions.py`、`tests/test_search_revisions.py`；Modify `research/numeric_catalog.py`、`numeric_integration.py`、`factual_premises.py`、`minimum_evidence.py`、`verification_tools.py`、`execution/verification_executor.py`，为新策略使用分离的 V2 分支。

**Interfaces:** `append_admission(record: ResearchRecordV2, admitted: AdmissionBatchV1, *, round_id: str) -> ResearchRecordV2`；
`recompute_revision(record: ResearchRecordV2, *, journal) -> ResearchRecordV2`；
`affected_roles(before: ResearchRecordV2, after: ResearchRecordV2) -> tuple[str, ...]`。
无增量返回原记录；材料及派生检查各最多一个快照；保留原计算、原条件及显式替代关系。

- [ ] 写 `test_recovered_financial_field_enters_check`、`test_new_price_fields_require_full_window`、`test_eight_snapshot_chain_limit`、`test_old_snapshot_hash_replays`。
- [ ] 写 `test_updated_value_rejects_old_numeric_receipt`、`test_unchanged_role_keeps_original_inputs`、`test_new_checks_do_not_resolve_economic_parent`；断言只有受影响输出需要新证明，派生计算不算独立来源。
- [ ] 运行 `python -m pytest tests/test_search_revisions.py -q` 取得失败，实现按快照和能力证明选择有效输入、重算指标和检查、发行新证明。
- [ ] 重跑新测试及 `tests/test_numeric_pipeline.py`、`tests/test_structured_financial_checks.py`、`tests/test_bounded_verification.py`，预期通过；旧版本固定 V0→V1 语义不改变，形成版本链提交边界。

## Task 7: 当前采集器接入初始搜索与接口失败回退

**Files:** Create `dataflows/search_sources.py`、`tests/test_search_source_routing.py`；Modify `execution/native_runner.py`、`research/native_record.py`、`dataflows/minimum_sources.py` 的有限扩展点，不改变旧采集器默认行为。

**Interfaces:** `SearchEvidenceSources(request, run_id, session, fetch, coordinator: SearchCoordinator)`；
`collect() -> tuple[ResearchRecordV2, Mapping[str, object]]`。
旧采集器保持原返回类型；新 runner 分支直接消费新记录，不能先把 V2 冒充旧 FreezeInputs／V1。
复用旧纯资格校验；缺失字段需求由宿主从实际采集结果生成。

- [ ] 写 `test_news_search_even_when_data_apis_succeed`、`test_failed_chain_search_recovery_once`、`test_partial_field_success_only_searches_missing_field`。
- [ ] 写 `test_identity_recovery_unique_before_company_materials`、`test_global_control_error_never_falls_back`、`test_default_current_collector_still_legacy`。
- [ ] 运行 `python -m pytest tests/test_search_source_routing.py -q` 取得失败，实现优先接口、已核实身份构造主题、缺口恢复及合格记录组装；取消／期限／持久冲突直接传播。
- [ ] 重跑新测试及 `tests/test_native_multisource.py`、`tests/web/test_native_production_wiring.py`，预期通过，形成采集提交边界；此时新路径仍由显式新身份测试启用。

## Task 8: 三轮补搜、专项复核与最终综合

**Files:** Create `execution/search_reviews.py`、`tests/test_search_reviews.py`；Modify `graph/native_research.py`、`execution/native_model.py`、`native_prompt_context.py`、`research/native_policy.py`、`unified_dialogue.py`、`unified_synthesis.py` 及 Task 1 的新版提议类型。

**Interfaces:** `run_search_reviews(record: ResearchRecordV2, gaps: tuple[EvidenceGapV1, ...], *, coordinator: SearchCoordinator, caller, ledger, cancelled) -> ResearchRecordV2`。
graph 注入这个能力，不导入 HTTP。新版专项／质疑／回应产物返回闭合 gap；原始专项→质疑→检查→回应后、最终综合前运行最多三轮。
`review` 阶段逻辑键包含 round／role／input snapshot hash；每个相关角色一个逻辑任务，实际尝试按本轮三次上限分配。

- [ ] 写 `test_three_rounds_then_no_fourth`、`test_no_qualified_delta_no_review`、`test_only_affected_roles_review`、`test_requests_from_reviews_feed_next_round`。
- [ ] 写 `test_retry_uses_third_slot_and_skips_unreviewed_role`、`test_resume_late_result_cannot_reopen_round`、`test_review_cannot_rewrite_original_condition`、`test_critical_conflict_remains_unresolved`。
- [ ] 运行 `python -m pytest tests/test_search_reviews.py -q` 取得失败，实现集中排队、调用协调器、追加／重算、相关角色复核及持久轮次状态；无增量提前停止。
- [ ] 综合阶段仅一次读取最新有效视图和各角色最近适用复核；撤回／修正旧推断不得继续肯定支撑。新风险明确未解决，保留未获复核的关键缺口。
- [ ] 重跑新测试及 `tests/test_native_specialist_isolation.py`、`tests/test_unified_research.py`、`tests/test_native_references.py`，预期通过，形成研究控制提交边界。

## Task 9: 记录发布、恢复及只读投影

**Files:** Modify `execution/record_publisher.py`、`native_publication.py`、`native_focus.py`、`output_publisher.py`、`runtime/reports.py`、`focus_artifacts.py`、`research/record_assembly.py`、`synthesis_sections.py`、`price_statistics.py`；以及 `web/research_record_projection.py`、`reader_stage_projection.py`、`reader_process_projection.py`、`reader_process_models.py`、`native_reader_versions.py`、`focus_projection.py`、`report_explanation.py`；Create `tests/test_search_publication.py`、`tests/web/test_search_projection.py`。

**Interfaces:** 所有持久边界调用 Task 1 `parse_research_record`；只在新身份下使用 V2 数值、检查及复核解释。
模型输入编译与公开投影分别接受明确 union，不能无条件 `ResearchRecordV1.model_validate`；旧记录路径保持旧结果。

- [ ] 写 `test_v2_publish_restore_project_export_same_record`、`test_legacy_saved_records_unchanged`、`test_read_focus_explanation_never_search`。
- [ ] 写 `test_unreviewed_new_evidence_not_claimed_as_reviewed`、`test_new_source_does_not_corrupt_legacy_price_projection`、`test_record_identity_tamper_rejected`。
- [ ] 运行两个新测试文件取得失败，逐个改消费者为版本派发，保存轮次、来源、回退程度、用量及停止原因；投影不得发起外部调用。
- [ ] 重跑新测试及 `tests/test_native_publication.py`、`tests/test_native_focus.py`、`tests/web/test_research_record_projection.py`、`tests/web/test_reader_process.py`，预期通过，形成持久化提交边界。

## Task 10: 前端契约、证据及过程展示

**Files:** Modify `frontend/src/api/contracts.ts`、`components/reader/NativeReader.tsx`、`ReaderEvidence.tsx`、`EvidenceDrawer.tsx`、`ResearchFlow.tsx`、`ReaderAgentOutput.tsx`；Create `components/reader/SearchResearch.test.tsx`；Modify `tests/test_frontend_wire_contract.py`、`frontend/e2e/fixtures/reader-fixtures.ts`；Create `frontend/e2e/search-research.spec.ts`；更新生成的 `tradingagents/web/static/`。

**Interfaces:** 后端标签联合 V1／V2 原样映射到 TypeScript，按版本收窄，无 `as any` 或临时重命名。
展示“初始双路／接口补缺／第 n 轮补证／相关专项更新／停止原因”；费用／HTTP 调试细节放审计，不加入预算编辑 UI。

- [ ] 写 `SearchResearch.test.tsx`：V1 正常读；V2 展示三轮、只恢复部分字段、单路降级和未复核状态，预期 DOM 不把摘要标原文。
- [ ] 执行 `npm --prefix frontend run test -- --run src/components/reader/SearchResearch.test.tsx` 取得失败，更新合同和对应组件；wire contract 测试固定新判别字段及上限。
- [ ] 新 E2E 以保存 fixture 验证切换旧／新记录、查看证据版本、预算结束保留待查事项；断言只读操作没有发起取数请求。
- [ ] 运行 `npm --prefix frontend ci`、`npm --prefix frontend run typecheck`、前端测试、`npm --prefix frontend run build`；用 Conda Python 设置 `TRADINGAGENTS_E2E_PYTHON` 后运行新 E2E，预期通过。
- [ ] 检查生成资产与源码一起形成前端提交边界；不把浏览器环境失败描述为功能通过。

## Task 11: 激活新工作流、文档同步及完整离线验收

**Files:** Modify `research/native_versions.py`、`execution/native_runner.py`、`execution/config_identity.py`、`runtime/catalyst_checkpoint.py`、`default_config.py`、`web/native_reader_versions.py` 的最终激活分支；Create `tests/test_dual_search_pipeline.py`；Modify `README.md`、`README.en.md`、`ARCHITECTURE.md`、`docs/README.md`、`docs/operations/evidence-research.md`、`docs/contracts/research-record.md`、`unified-company-research.md`；Create `docs/contracts/dual-search-research.md`。

**Interfaces:** 新创建／重试的新研究选择 `evidence-production-v8`，历史 resume 从持久身份选择原实现。
新的冻结配置包括查询、端点、深度、全部池、时间及准入／数值策略；不得把旧 resume 自动升级。
配置缺 key 降级，取消和新研究禁用开关仍生效；batch 子研究独立计量但共享既有进程并发限制。

- [ ] 写 `test_new_web_batch_uses_v8_legacy_resume_v7`、`test_all_pools_enforced_end_to_end`、`test_recovered_data_changes_checks_and_review`、`test_both_services_unavailable_honest_partial`；离线假服务贯通全部阶段、发布、读取和导出。
- [ ] 运行新集成测试取得失败，接通最终版本选择并同步说明；仅当之前任务验证通过才激活新默认。
- [ ] 使用 Conda 运行 `python -m pytest`、`python scripts/check_agent_docs.py`、`ruff check tradingagents cli scripts/check_agent_docs.py`；运行 frontend typecheck／test／build 及受影响 E2E。预期均通过；若全套有失败，区分既有与新增并保留证据，不宣称全套通过。
- [ ] 执行 `git diff --check`、`git status --short`，确认只包含本功能及构建资产；核查没有凭证／真实用户数据／付费调用记录。
- [ ] 发布前另按授权执行代码审查与 Git 流程。真实质量验证另用有限样本比较有效新增材料、字段恢复正确性、推断修正、延迟与实际用量；本计划的离线通过不能替代该结论。

## 自审与执行顺序

- 设计第 1／7 节预算对应 Task 1–3；第 3／4 节路由对应 Task 3／4／7；第 5 节三轮对应 Task 8。
- 第 6 节数据回收对应 Task 5／6；第 8 节版本与证明对应 Task 1／6／9；第 9 节展示与激活对应 Task 9–11。
- 第 10 节验收逐项落入任务测试；五项 Review Focus 均已绑定测试。本文函数／返回类型由接口地图及拥有任务定义，所有任务共用同一组契约。
- 执行顺序为 1→2→3→4→5→6→7→8→9→10→11；互相依赖的契约不并行改写。
- 推荐 Native：同一执行者连续处理接口与版本迁移，结束后做一次独立整体代码审查。若选择逐任务子代理，则每任务实现后先过独立审查再继续。
- 计划制定时仅完成编写与静态自审；当时列出的测试是预期验收步骤。最终执行证据见上方收尾记录。
