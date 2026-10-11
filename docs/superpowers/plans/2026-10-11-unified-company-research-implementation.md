# 统一公司研究实施计划

- Status: Historical
- Do not use this document as evidence of current implementation behavior.
- 已批准设计：[统一公司研究](../specs/2026-10-11-unified-company-research-design.md)。
- 当前行为：[文档索引](../../README.md)。

## 实施顺序与验证

1. 新增封闭 dialogue/response/adjudication/V3 assessment 契约、版本/预算与版本化四维策略。保持旧字段省略、旧维度和旧版本常量。验证无效引用、撤回/修正支持、公开条件及旧序列化。
2. 接入一轮专项回应和综合资格：作者绑定、固定顺序、有界并发、缓存/未知派发、effective support、V3裁决和倾向gate。验证零挑战、多挑战同角色、三个回复、失败与恢复。
3. 接入V7 NativeRunner、模型schema、任务投入、ledger、角色事件、观察统计、focus、publication和Markdown。验证8/1/12、旧V6恢复、取消与发布。
4. Web单个/批量/重新研究拒绝旧新建mode；读取与恢复不受影响。更新公开record/process/agent/Reader资格策略、TS镜像。
5. 移除新建模式与持仓表单，新增四维投资判断与质询追溯，按保存版本显示回复角色。验证Vitest/Playwright、390px、键盘焦点。
6. 同步中英文README、架构、操作/契约/索引，build生成资产。运行docs/Ruff/typecheck/build、相关pytest/Vitest/Playwright与diff检查。

## 工作边界

仅修改本任务文件，保留无关untracked与用户数据。不启动付费研究，不重放历史派发，不自动提交或远端发布。按步骤实现并验证，记录实际结果；测试通过不等于投资研究质量验证。


## 本地实施记录（2026-10-11）

上述六步已在本地完成。新建只接受公司研究，V7 四维投资判断、一轮定向回应、引用/撤回/条件门控、版本化预算与角色、Reader/Markdown、历史恢复和文档已接线。已通过 Python 全量 3378 项及 74 个 subtests；随后新增统一研究/SDK/未知派发回归共 12 项，并通过最后一轮 69 项针对性回归。Vitest 338 项、Playwright 6 项（1440/1280/390/720px）及 docs/Ruff/typecheck/build 均通过。Chromium 在 macOS 沙箱内启动失败后，在允许的测试环境通过。当前契约见 [统一公司研究](../../contracts/unified-company-research.md)。这是工程验证，不是付费模型研究质量评估；未启动真实研究、未提交或远端发布，也未修改用户数据或旧报告。
