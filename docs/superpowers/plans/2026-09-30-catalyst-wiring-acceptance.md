# 催化研究真实接线：工程验收与接力记录

Status: Historical

日期：2026-09-30。这是实测记录，不是当前运行契约；当前行为见
[操作说明](../../operations/catalyst-research.md)及 [ARCHITECTURE](../../../ARCHITECTURE.md)。
范围以[批准设计](../specs/2026-09-30-catalyst-production-wiring-design.md)为准。

## 已落地路径

显式 Web profile → `CatalystRunner` → 有界真实来源/模型适配 → 冻结证据 →
三个专项 → 独立反证 → 单次综合 → canonical 校验 → durable 发布 →
`/catalyst`、工作台及同源 Markdown。classic 仍为默认，旧 CLI/facade 不会
把 catalyst 冒充 classic。问题、profile/policy、模型配置及 cutoff 随重试/恢复保留。

恢复始终继承预算，四阶段结果可复用。取消与发布授权共享生命周期锁。
未知 dispatch 保守计费，恢复重做主调用消耗独立网络重试许可。
相同逻辑任务或公开产物出现不同内容时拒绝；持久化失败不继续 dispatch。
已发布 artifact 必须是 committed 事件，读取不触发计算。

## 验证证据

| 验证 | 实际结果 | 范围 |
| --- | --- | --- |
| Python 聚焦回归 | 186 passed | workflow、budget、classic regression、HTTP profile、fixtures、生产接线与投影；模型和来源使用明确 fixture |
| Vitest | 41 files / 298 passed | 表单、请求、读取、阶段、取消与中断动作、引用/抽屉等 |
| Chromium + 实际 HTTP/SSE/store | 6 passed | 1440×900、1280×800、390×844，创建请求、七行简报、引用/Esc/焦点返回、刷新后重选同一 run、classic 状态保留、取消后无结论 |
| 缩放等价布局 | 720×450 CSS pixels / DPR 2，通过 | 对应 1440×900 的 200% 可用空间；全部行可滚动读取，无横向页面溢出。**不等于原生 Chrome 200% 缩放已验证** |
| 四阶段进程退出 | 全部通过 | evidence/specialists/refutation/synthesis 持久化后分别退出；恢复不重复完成的调用 |
| 发布屏障后退出 | 通过 | 恢复只补发布，零新增来源/模型调用 |
| 取消/发布竞态 | 两种顺序均通过 | 取消先到禁止公开 case；授权先到晚取消冲突 |
| timeout / corruption / conflict | 通过 | 超时后的来源返回不发布；恢复坏哈希/身份拒绝；许可持久化失败零 dispatch；不同内容拒绝 |
| SDK/来源边界 | 通过 | retries=0、真实 HTTP dispatch 计数、thread config/provenance、单次结构修复、cutoff 行过滤、逐公告引用、未选源不替换 |

真实浏览器发现并修复了关闭抽屉后背景仍 inert、焦点无法返回的缺陷；
同时补齐研究问题文本框宽度和焦点样式。浏览器 screenshot 位于被忽略的
`frontend/test-results/`，可重跑 `frontend/e2e/catalyst-wiring.spec.ts`。
服务器 fixture 为 `scripts/catalyst_e2e_server.py`，使用隔离临时 run store，
所有研究内容明确标为 synthetic，不作为真实研究质量证据。

原生 Chrome 缩放仍待人工验证：browser-harness 在 daemon socket 清理时触发
目录权限限制；之后观察到用户正在操作原生 Chrome，没有继续切换或改变其页面。
未把等价 viewport 或 headless browser 写成原生缩放证明。

## 一次有限真实试跑

- Run：`run_20260930T060128040479Z_f547433e`，`600519.SS`，cutoff `2026-09-30`。
- 真实中立 production runner、manager、LLM 与来源；不是 synthetic 模型。
- 沿用 DeepSeek V4 Flash quick/deep、thinking enabled、effort high。
  仅本次响应 cap 为 8192 tokens，active deadline 300 秒；未改全局配置。
- 实际 dispatch：3 次主模型、1 次结构修复、3 次数据能力、4 次 HTTP。
  SDK 自动重试关闭；没有本轮范围外的批量付费运行。
- 身份及巨潮公告覆盖 qualified；8 条冻结证据、7 个披露事件。
  财务 unavailable；默认链无有界合格行情适配，行情 unavailable；专项有失败。
- 结果 `completed / ready`，但研究为 **partial / LOW_CONFIDENCE /
  insufficient_information**。Markdown 报告已生成；重复读取没有新增尝试。
- 已返回 usage 的合计为 1323 input / 1821 output tokens；失败/修复等缺失
  usage 不可据此推断为零，以上不是整次计费或成本报告。
- 临时证据目录：`/var/folders/rc/7jzjpb091nb90mnz7ymc2byr0000gn/T/catalyst-live-smoke-20260930-ok4ix9kk`。
  safe summary、checkpoint、事件与报告保存在此目录；没有搬入仓库。

这次证明真实取数/模型尝试、失败约束、发布与读取链路，不证明完整研究质量，
也不证明 catalyst 比 classic 准确。默认价格适配当前没有可通过的资格路径；
即使有凭据，也不能据此声称财务权限可用或历史复权 PIT 已验证。

## 回归基线与门禁

实施前基线：15 failed / 2319 passed / 73 subtests。
最后一次全量：16 failed / 2345 passed / 73 subtests。随后补非对象 checkpoint 的稳定拒绝保护，聚焦 186 项重验通过。原有 15 项失败全部保留；
另有 `test_explicitly_disabled_returns_data_unavailable` 随东方财富端点可用性失败。
直接在隔离导出的 `168326c` 原代码上跑 live 测试为 1 passed，说明端点可用性
不能稳定重现。随后在该基线的网络边界注入明确标注的有效备份 fixture，同一原测试
复现失败：禁用 Wind 后备份返回有效指数数据，而测试期待 DATA_UNAVAILABLE。
被测 interface、registry、index_provider、default_config 和测试文件与 `168326c`
无差异；归因为既有测试依赖外部端点可用性，未把 fixture 复现写成真实取数证明。
原交接也记录过此偶发项。
其中三项 Web CLI 失败源于 sandbox 禁止写既有用户 server.log，单独允许执行时
该文件 8 passed。其余原有失败涉及 graph 测试预期、冻结 runtime 指纹、skills
metadata、Wind skill hash/version 和 live EDB。未通过改这些测试隐藏失败。

本轮运行 `npm ci`、typecheck、build，重建 tracked static；Ruff、agent-doc
检查与 diff-check 使用最终文件。仓库不存在 CHANGELOG，因此同步双语 README、
架构、docs 索引、操作说明、批准设计与旧交接顶部更正，不新建空 changelog。

原始日志在 `/private/tmp/`：

- `catalyst-wiring-focused-final.txt`
- `catalyst-wiring-vitest.txt`
- `catalyst-wiring-playwright.txt`
- `catalyst-wiring-live-smoke.txt`
- `catalyst-wiring-baseline-20260930.txt`
- `catalyst-wiring-regression-final-20260930.txt`
- `catalyst-wiring-wind-baseline-repro.txt`
- `catalyst-wiring-wind-baseline-fixture-repro.txt`
- `catalyst-wiring-webcli.txt`

## 剩余决策与边界

1. 原生 200% 缩放人工操作与阅读复查仍待完成；等价尺寸已通过。
2. 要得到完整真实研究，需新增可审计预算、覆盖与历史复权因子证明的行情适配，
   并解决财务来源权限/覆盖问题。不能取消资格门控来获得 PASS。
3. T33 架构/产品对照、replay 语料建设、额外付费预算、T34 真人阅读验收和默认
   切换继续需要原交接 C-1～C-4 的产品决定；本轮没有宣称这些完成。

实现与设计都是本地工作；没有推送/PR，没有修改全局凭据/供应商配置或清理
历史 worktree 与用户数据。后续从以上待验/决策继续，不要重做接线或把部分结果当完整。
