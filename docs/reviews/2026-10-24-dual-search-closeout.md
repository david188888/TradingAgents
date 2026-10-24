# DeepSeek/Tavily 双路搜索实施收尾

Status: Historical — 2026-10-24 的实现、审查与发布前知识凭证。
**Do not use this document as evidence of current implementation behavior.**
现役行为以[双路搜索合同](../contracts/dual-search-research.md)、代码和匹配版本的测试为准。

## 交付与进度

[设计](../superpowers/specs/2026-10-23-dual-search-research-design.md)及
[实施计划](../superpowers/plans/2026-10-23-dual-search-research.md)的任务 1–11 已完成。
任务测试名与接口在实施中按实际拥有层调整；原计划保留制定时的命名与步骤，不再是开放待办。
实现原先保留为未提交工作，本次按用户授权集中形成 v3.7.0 发布提交，不伪造逐任务提交历史。

| 任务 | 交付与证据 |
| --- | --- |
| 1 契约 | 闭合搜索/缺口/资格/复核类型与 V2 追加式记录；V1 兼容测试 |
| 2 预算 | 持久原子预留，服务/正文/模型/HTTP 父子池，搜索活动并集时间与恢复 |
| 3 供应商 | 独立 Search/Fetch/Extract、实际请求计量、公开地址与 PDF 下载边界 |
| 4 协调 | 双路查询、去重、缓存、单路降级、未知派发不重发 |
| 5 字段恢复 | 原文、证券代码、期次、单位、币种与口径准入；不支持的需求保持缺失 |
| 6 证据修订 | 字段资格首次生效版本、比较计算、冲突、检查历史与快照特定数值目录 |
| 7 来源路由 | 专用接口优先、仅缺失字段回退、新闻/行业初始双路搜索 |
| 8 补证复核 | 共享三轮，只调用受影响专项，重试计入每轮上限，最终综合一次 |
| 9 发布投影 | V2 持久发布、恢复、Reader、关注点、解释与 Markdown；历史版本分派 |
| 10 前端 | 搜索、资格、复核、版本与待查项；桌面/窄屏和只读浏览器验收 |
| 11 激活与验收 | 新单公司/批量默认 V8、冻结配置及关闭选项、全套离线验证 |

## 独立审查与修复

一次独立整体只读审查确认五项 Important，无确认的 Critical 或需延期 Minor。
五项均在集中修复中覆盖：Tavily 日期请求和实际格式、当前冲突使旧算术失效、后来资格不得改变
历史目录、取得正文后归并转载、可选 PDF 网络错误降级但完整性/取消/全局截止继续传播。
另补充三个真实受影响角色的共享预算测试；第一个复核的重试占用第三次后，第三个角色保留未复核状态。

修复后的完整验证：Python **4012 passed / 74 subtests passed**；前端 **402 tests / 59 files passed**；
受影响 Playwright **21 passed**；wire contract **10 passed**；typecheck/build、Ruff、文档与 diff 检查通过。
旧浏览器模拟解释器修复了 JSON 后追加提示文字的解析问题；旧断言对齐保存的“解释假设”标签。
两项后台生命周期测试原有短等待在全套运行中超时，单独重跑通过；仅调整测试等待窗口，未弱化语义断言。

## 知识面状态（发布前）

| 事实面 | 状态 | 核验/边界 |
| --- | --- | --- |
| 代码 | verified-current | 当前功能分支、V8/V2 schema、完整离线测试与五项修复 |
| 运行态 | out-of-scope | 本地 8765 `/api/config` 只读探测返回 200；无 release commit marker，未重启，不能声称加载本版本 |
| 文档 | changed-and-verified | 双语 README、架构、Reader、来源能力、合同/运维索引、历史设计和计划均对齐 |
| 规则 | verified-current | CLAUDE 导入根 AGENTS；Python/前端 scoped guide 有效；保留现有同源结构，无新增规则副本 |
| 记忆 | out-of-scope | Codex 生成记忆只读；Hindsight 使用官方自动 hooks，不重复写回或改配置 |
| 工作区 | pending | 已盘点当前分支及六个其它关联工作树；其它工作树只读保留，发布后再预览精确清理对象 |

## 发布验收与未覆盖项

目标 v3.7.0，沿用仓库既有 squash PR 合并和 GitHub Release/源码归档渠道。
GitHub 当前无 Actions、分支保护或 ruleset；此状态不是远端 CI 通过。
真实付费搜索/模型、生产研究质量、部署/服务重启、历史数据迁移和 F01–F07 总体结项均不在本次验收内。
依赖与构建警告见[发布说明](2026-10-24-v3.7.0-release-notes.md)。

版本收尾验证：三处版本为 3.7.0，锁文件依赖树与基线完全一致；npm ci、前端 402 项测试、
typecheck/build 及 30 项打包/CLI/wire 测试通过，176 篇 Markdown 检查与 Ruff/diff 检查通过。
首次提交门禁进一步检查了全部改动 Python 文件，修复测试夹具的 import、字面量和未使用变量，
并移除随即被覆盖的错误闭包 mock；相关搜索/实际运行器/投影 **123 项重跑通过**，未绕过 hook。
隔离源码副本成功构建 wheel/sdist；元数据为 3.7.0，V2 schema、协调器、codec 与 SPA 文件
和工作树逐字节相等。构建产物仅本地验包，不上传为 Release assets。
发布后的 PR、merge commit 与 tag 以 GitHub 的最终记录为准，不能由本发布前凭证推导。

只读清场候选：合并后的本功能分支及 `.superpowers/sdd/2026-10-23-dual-search-research/` 审查/测试现场。
计划与设计保留为可检索历史，不自动移动或删除；原有六个工作树不属于本次清场范围。
上述为发布前的清场预览；后续授权与执行结果见下节。

## 发布及确认清理结果（2026-10-24）

- [PR #34](https://github.com/david188888/TradingAgents/pull/34) 已 squash 合并，
  合并提交为 `7dc83362f7dbc4ce733d100d83e8a32a3d4a5347`。
  [v3.7.0](https://github.com/david188888/TradingAgents/releases/tag/v3.7.0) 已正式发布，
  标签指向该提交；本条收尾记录随后同步到主线，不移动或重发版本标签。
- 用户在看过最终汇报及精确清理预览后明确回复“同意清理”。执行前重新核对 PR 已合并、
  功能分支与主线内容一致、远端分支 SHA 未改变，以及清理路径不包含跟踪源码。
- 已删除本地及远端 `codex/dual-search-research` 功能分支。
- 已删除本次执行/审查日志目录、浏览器 `test-results` 与 `playwright-report`，以及隔离构建副本、
  盘点文件和两份依赖审计输出，共七处确认的临时路径；删除后逐项复核不存在。
- 清理完成时，本地 `main`、`origin/main` 和 `v3.7.0` 均指向上述发布提交，跟踪工作树干净。
  原有六个其它关联工作树、用户配置及研究数据均保留。设计、计划、发布说明和本收尾记录继续归档。

发布前事实矩阵中的“工作区 pending”至此已完成本次确认范围内的清理；其余运行态、记忆、
真实付费研究验收及依赖/构建警告边界不变。本次仅同步文档，不表示服务已重启或部署。
