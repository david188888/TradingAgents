# 数据源与证据研究重构：本地整合验收

Status: Historical

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

> 编写时状态：Historical

Do not use this document as evidence of current implementation behavior.

日期：2026-10-02。当前行为请从 [docs 索引](../../README.md)、[数据能力](../../operations/a-share-data-capabilities.md)、[共享记录契约](../../contracts/research-record.md)及代码查证。

## 合并与修改归属

整合分支：`codex/research-data-integration-20261002`，起点 `main b68fee8`。工作区原有修改已先逐文件备份到临时目录，再保存为独立提交；未删除用户数据或改写来源分支。本记录描述本地整合，没有发布远端或修改 `main` 的引用。

| 提交 | 内容 |
| --- | --- |
| `90d0199` | 原有 A 数据/量化基础、B 共享记录、有限 D Reader 和已认可的样稿/方案 |
| `78038c6` | 合入 `feat/a-stock-data-v3.10-sync` tip `4b2fcb8`，保留八条原始提交；唯一冲突为 docs 索引，双方入口均保留 |
| 后续整合修复 | 历史日期保护、Sina 空页歧义/请求串行、腾讯日历周期分页、显式复权数值检查、发布失败事件契约；实际提交用 `git log main..HEAD` 查询 |

数据源分支包含 mootdx 财务/行情探测隔离、聚宽后缀和错票保护、F10 文本/类别校验、事件与官方补充接口、腾讯日/周/月 raw/qfq 独立路由、严格东财 datacenter 分页和 `ScreeningCoverageV1`。新增接口目前可由 meta-tool 关键词或直接路由触达，没有自动纳入 supplement prefetch 或 bounded catalyst 必需能力。

原有研究改动包括 Tushare dated-factor/交易日资格校验、代码计算的风险与 ATR 指标、Wind CLI 2.0.4 契约修正，以及三模式共享记录的发布/恢复/只读投影。Reader 首先显示已保存来源内容，并展示合格且已持久化的催化价格统计；无数据时保留缺失原因，旧报告不编造正文。

## 合并审查追加保护

1. 六项实时/最新 meta 工具不再让历史研究读取今天的数据：业绩预告、回购、质押、IPO、上证e互动、新浪研报。校验发生于供应商 dispatch 前，以上海当前日期判断。非法/未来日期同样拒绝；bundle 原有日期收敛规则保留。机构调研保留 `NOTICE_DATE` 窗口过滤，不宣称历史 vintage 得到证明。
2. Sina 同一空页可能表示无数据或限流；一次间隔重试不能证明没有研报，因此明确不可用。有效记录仍为 partial。锁与单调时钟覆盖请求间隔、HTTP 和一次重试，避免并发绕过间隔。
3. Tencent 周/月翻页改用上一日历周期终点，不按固定 7/31 天减。短交易周和不同月长的离线 fixtures 验证所有已提供 bar 都被保留；仍保留 qfq/raw 口径拒绝与预算边界。
4. `apply_adjust` 拒绝非有限/非正因子，以及非有限输入价格/溢出结果。显式复权换算不构成因子 vintage 或来源资格证明。
5. 共享记录发布失败的 `artifact.projection_unavailable` 事件补齐 Python 必需字段和 TypeScript payload union。记录失败保持可审计，原已提交 case 继续可读。

## 验证

使用同一 conda tradingagents Python 环境和相同命令，在临时解包的 `b68fee8` 基线及整合工作区比较失败集合；未 stash 或 reset 工作区。命令：

```bash
PYTHON_DOTENV_DISABLED=1 python -m pytest -m 'not smoke' --deselect=tests/test_deepseek_reasoning.py::TestDeepSeekLiveStructuredOutput -q --color=no -p no:randomly --tb=short
```

基线：**14 failed / 2343 passed / 5 deselected / 73 subtests**。已记录来源与环境不同的旧分支数字仅为历史数据，本次不以其作为门槛。

整合：**12 failed / 2660 passed / 5 deselected / 73 subtests**。新增失败集合为空；基线 Wind manifest hash / skill version 两项已随 2.0.4 契约同步修复。仍有 12 项基线失败：graph prefetch 顺序 3 项、fundamentals 历史日期文本 1 项、runtime v2 描述/指纹/恢复预期 3 项、methodology 字段预期 2 项、Web CLI 本地日志写入权限 3 项。**全量 pytest 没有全绿**；本批未扩展到这些既有问题。

针对性数据源/量化/共享记录/生产接线组合：**578 passed / 4 smoke deselected**。补齐发布失败事件后的契约/保护子集 **156 passed**（与前项有重叠，不相加）。前端 **43 文件 / 309 测试通过**；`npm ci`、typecheck、build、Ruff、文档检查（61 页）与 `git diff --check` 通过。生成 static 已包含在 `90d0199`，再次构建字节无变化。

验收中修正两项测试隔离问题：共享记录 HTTP 合成夹具须标为 completed，防止正常启动恢复意外创建后台任务污染下一项客户端 mock；禁用 Wind 的测试将路由固定为 Wind，避免默认 EastMoney 的真实 fallback 成功造成错误失败。生产恢复和模型调用次数断言未放宽。

初轮全量检查纳入了既有真实 DeepSeek 集成测试，未将结果作为研究质量/准确率证据；最终比较已显式排除该 class，并关闭 `.env` 自动加载。这是测试边界检查的修正。其余结果也不构成供应商权限/PIT 的重新认证。本批不执行付费模型对照或新的真实数据权限认证。npm lockfile 安装仍有既有 16 项审计告警；构建有主 chunk 超过 500 kB 的提示，未扩大为依赖升级/拆包。

## 下一阶段

research-only 与 classic 默认保持。当前已完成基础层与兼容共享记录、部分 Reader；**独立验证执行器、共用三模式研究内核、完整统一 Reader 和质量/成本对照仍未完成**。数据源合并不代表研究准确率提高。下一步继续 C 流程层，在冻结 V0 证据之后生成可反驳假设，针对关键挑战执行有界核查，并保存 V1/验证结果；随后完成 D/E。详见 [实施计划](../../superpowers/plans/2026-09-30-evidence-driven-research-implementation.md)。
