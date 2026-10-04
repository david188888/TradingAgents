# C2 原生三模式研究：公开接线验收

Status: Historical

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

> 编写时状态：Historical

Do not use this document as evidence of current implementation behavior.

日期：2026-10-03。接续 `a549afb` 的[共享内核验收](2026-10-02-native-research-kernel-acceptance.md)和[接线清单](../plans/2026-10-02-native-research-wiring-implementation.md)。用户确认采用独立 `evidence_v1`；当前行为查[操作说明](../../operations/evidence-research.md)及[记录契约](../../contracts/research-record.md)。

## 实施范围

独立数据政策固定公告 7/30/90 日回看、行情 250 交易日和财务最多 8 期，不把催化 84 天展望套在公司或持仓研究。canonical request、snapshot、API、factory、metadata、恢复/重试、角色事件、TypeScript 和 Reader 均接入公司研究、催化研究、持仓复盘。Web 通过 `TRADINGAGENTS_EVIDENCE_ENABLED=true` 显式开放创建；省略 profile 仍是 classic，不增加用户选择器，旧 catalyst_v1 的执行/恢复保留，CLI 未新增 profile 参数。

NativeRunner 复用已有合格 source collector、可观测 transport 与同一本 durable ledger。原始 source 响应按精确 JSON 文本保存以抵抗 RFC8785 数值规范化；模型 dispatch 前保存 facts-only V0。恢复复用源/阶段/候选，未知已派发请求保持消费，不能自动重派。模式、问题、政策、配置、期限、持仓声明进入身份；不兼容恢复拒绝。

新路径使用六个 native 状态角色，实际研究内核仍是三个窄专项→一次匿名挑战→有界条件核查→一次综合。没有第二个报告摘要模型。Native public record 为必需发布，Reader 与 Markdown 同源。Native Reader 单独作为主报告，不挂旧 classic/catalyst case；首层包含判断、依据、主要疑点、下一核查和已保存量化，来源先显示已保存内容。没有实施完整 D 浏览器/布局验收或 E 质量/成本对照。

## 独立审阅与保护

独立只读审阅发现并修复：已提交记录在 interrupted resume 时跳过当前生命周期发布仲裁；新 profile 的 LOW_CONFIDENCE/partial 仍显示成功研究；非法原持仓声明先取数后被拒。另补程序入口跨证券持仓拒绝（接受同证券 SH/SS/裸代码写法），并同步 TypeScript 六个新增 API 错误码。新增回归覆盖这些边界。新原生 seed 与 request 身份必须匹配，存档 native snapshot 缺少 policy 身份不能静默补默认。

实际 HTTP→真实临时 RunStore/RunManager→NativeRunner→record→只读 API→同源 Markdown→retry 的三模式串联使用确定性来源和模型替身；恢复覆盖 seed 保存前、最终候选保存后、公开 record 已提交但 run.completed 前；已提交记录复用仍重入生命周期仲裁。取消先赢时阻止本次最终发布，授权先赢时拒绝取消。全缺来源可以结束流程，但保留 partial/LOW_CONFIDENCE、空事实与明确证据限制提示，不宣称研究质量通过。

## 验证结果

最终针对性内核/请求/HTTP/真实 manager/恢复/投影/旧 profile/前后端 wire 契约组合 **281 passed**，其中本批新增 Python **66 项**。前端 **45 文件 / 325 项通过**。npm ci、typecheck、build、Ruff、文档检查（69页）与 diff check 均通过；生成 static 同批保存。验证属于临时实际持久化存储、Python/组件检查；未做真实浏览器 E2E，也不代表供应商资格或研究准确率已验证。

最终全量离线 **12 failed / 2930 passed / 5 deselected / 73 subtests passed**。与 a549afb 共享内核阶段 **12 failed / 2864 passed** 比较，失败 ID 集合完全相同，没有新增失败；仍保留 graph prefetch 3项、fundamentals 日期文本1项、runtime v2契约/恢复3项、methodology metadata2项、Web CLI本地日志权限3项。**全量并未全绿。** 两个旧 profile/mode Literal 断言随明确新增入口更新，但 classic 默认、学习模式集合和旧指纹约束保留；错误码镜像的现有测试发现漏项后修复。最终测试均关闭 dotenv、排除 smoke 和未标记 live DeepSeek class。

最终日志：`/tmp/tradingagents-native-public-final-tree-offline-20261003.log`、`/tmp/tradingagents-native-public-final-tree-regression-20261003.log`。基线日志：`/tmp/tradingagents-c2-final-offline-20261003.log`。前端日志：`/tmp/tradingagents-native-vitest-20261003.log`、`/tmp/tradingagents-native-final-build-20261003.log`。保留既有 npm audit 16项（4 moderate / 11 high / 1 critical）及主 chunk 511.06 kB 构建提示，本批未升级依赖或拆包。

## 后续边界

完整 D 的真实浏览器阅读/布局验收、E 同证据研究质量与成本对照、付费模型与供应商评估、默认迁移尚未执行。本批只做本地提交，不 push、不修改 main，不宣称研究准确率提高。
