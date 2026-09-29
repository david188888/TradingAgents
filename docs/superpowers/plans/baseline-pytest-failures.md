# pytest 基线失败清单（2026-09-29，ca90f27，改动前）

- 命令：`python -m pytest -q -p no:randomly`（conda env `tradingagents`，Python 3.13.13，pytest 9.0.3）
- 结果：**15 failed / 1983 passed / 73 subtests passed / 19 warnings，80.27s**
- **修正（2026-09-29，agent B 实测）**：真实稳定基线是 **14 failed**，不是 15。`test_wind_provider.py::TestConfigFlag::test_explicitly_disabled_returns_data_unavailable` 属偶发失败——单独运行通过（33.57s），在 pristine tree 上跑全量也不复现。B 通过 `git stash push -u` 清空工作树后重跑确认：**14 failed / 1984 passed**，与上述同一组。判定门槛按 14 计。
- HEAD：`ca90f27`（本次工作只新增 docs，未触碰任何被测代码）

## 失败分类

### 1. Wind 合约漂移（5 项）— 与项目记忆「wind ×3 B 类待验」吻合
- `test_wind_provider.py::TestContractHashes::test_manifest_hash` — tool-manifest.json 哈希变了
- `test_wind_provider.py::TestContractHashes::test_skill_version_constant` — cli.mjs SKILL_VERSION 与 provider 常量 `'2.0…'` 不一致
- `test_wind_provider.py::TestLiveSmoke::test_live_edb_search` — WindError [UNKNOWN]
- `test_ollama_base_url.py::test_confirm_endpoint_warns_on_missing_scheme`
- `test_ollama_base_url.py::test_confirm_endpoint_warns_on_non_default_port_remote`

### 2. Graph 路由顺序（4 项）— 预取节点插入改变了 analyst 顺序
- `test_a_share_supplement_prefetch.py::test_graph_runs_supplement_prefetch_once_before_first_analyst`
- `test_evidence_steward.py::test_graph_routes_last_analyst_to_evidence_steward_before_debate`
- `test_market_price_prefetch.py::test_market_graph_forces_price_prefetch_before_analyst`
- `test_fundamentals_lookahead.py::test_both_vendors_withhold_on_the_same_rule`

### 3. Runtime 指纹冻结（3 项）— **与本次重构直接相关**
- `test_runtime_scaffold.py::test_production_v2_descriptor_and_delta_are_frozen` — `a_share_supplement` 进了 profile 列表
- `test_runtime_scaffold.py::test_production_v2_fingerprint_bytes_are_frozen` — 指纹字节 `fc2fcd10…` ≠ `cc5d8b11…`
- `test_runtime_scaffold.py::test_checkpoint_authorization_is_bound_to_prepared_context`

### 4. Skills registry 契约（2 项）
- `test_skills_registry.py::test_methodology_artifact_contains_only_selected_contract_metadata`
- `test_skills_registry.py::test_methodology_artifact_uses_existing_observer_only_when_context_is_active`

## 对设计的意义

T25/G9 要求「classic 全部既有测试全绿」作为硬门槛。**当前基线本身不是全绿**（15 红）。
判定标准因此改为：**本次变更不得让这 14 项变差，也不得新增失败**。
B/C 触及 runtime 指纹与 policy 的任务必须特别小心第 3 类——它们已经是红的。
