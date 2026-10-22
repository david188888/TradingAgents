# F02／F04 接力改进：知识与工作区收尾

Status: Historical

日期：2026-10-23。本次为用户指定 `neat-freak` 的知识收尾，不是发布或破坏性清场。
核对基于 `codex/v8-phase0`、HEAD `e8c283d` 及已有未提交工作；不把本记录当作现役架构来源。

## 范围与权威入口

本次只收尾此前 F02 遗留修复、F04 只读计量与可逆元数据离线切片，以及本机缺失技能的修复。
不扩展到其他项目或 linked worktree 内容审查，不新增模型运行、生产启用、存储迁移或预算政策。

- 当前行为：[计量与离线比较契约](../contracts/native-input-measurement.md)、
  [事实前提契约](../contracts/factual-premises.md)及各自 canonical 代码。
- 离线证据：[F04 实施验收](2026-10-23-f04-metadata-view-validation.md)与机器报告，
  [F02 接力修复](2026-10-22-remediation-handoff-validation.md)。
- 仍开放的整改：[整改待办](../plans/2026-10-21-review-remediation-backlog.md)。
  生产接入、真实 tokens/质量及综合修复预算未关闭；F03 人工标注、F05、F07 与 P3 保持原边界。

## 六个事实面

| 事实面 | 状态 | 证据与限制 |
| --- | --- | --- |
| 代码 | `verified-current` | F04 codec 仅被离线脚本和测试引用；F02／F04 相关 10 个测试文件本轮 154 项通过；未修改实现或校验 gate |
| 运行态 | `pending` | CLI `--help` 可运行；现有 8765 服务首页 HTTP 200、HTML 与 checkout 静态入口逐字节相等、两份引用资产存在。未验证 Python 进程加载的修订或 F02 真实用户路径，不能推导已部署；F04 未接入生产 |
| 文档 | `changed-and-verified` | 修正 F04 总表及技能缺失的过期摘要，历史接力记录增加后续指针；现役机制仍只在原契约解释 |
| 规则 | `verified-current` | 全局 Codex AGENTS 引用 RTK，根 CLAUDE 导入根 AGENTS；Python/frontend scoped 规则存在；敏感本地配置被忽略且未跟踪；本轮未改规则、hook 或全局配置 |
| 记忆 | `pending` | Codex 生成文件保持 `generated-read-only`；Hindsight 正式 correction 已接收，自动知识页复读尚未反映完成状态，不能宣称异步刷新已完成 |
| 工作区 | `pending` | 起始完整状态含 148 个路径（69 修改、2 删除、77 未跟踪）；本轮只修改下列文档，其他起始文件哈希保持不变。保留 6 个既有 linked worktree；未提交、发布或清场 |

未涉及的新部署、真实模型对照、整个 workspace 审计及其他 worktree 的集成性审查均为 `out-of-scope`。
本轮不是产品功能变化，无需为离线表示再改两份 README 的产品概述或重建前端。

## 消除的状态漂移

| 权威事实 | 过期表面 | 处置与验证 |
| --- | --- | --- |
| F04 离线 codec 和完整 prompt 对照已存在，生产未接入 | 整改总表仍称“视图待设计” | 更新总表、核对日期及证据指针；不勾掉预算、生产或质量验收 |
| `writing-plans` 与必要流程依赖已在本机安装并可发现 | F04 方案末尾仍用现在时称技能未安装 | 改为实施当时的历史原因，补记本机修复；明确不是产品运行依赖，也不追认过去执行过该技能 |
| 10-22 的初始 F04 建议已经推进 | 接力历史记录仍列计量为下一步 | 保留原文并增加 10-23 后续指针，避免改写历史测试数值 |
| F04 记忆页只记录到获批实施 | 自动知识页缺少离线交付状态 | 经正式 correction 接口提交代码路径、权威契约、机器报告哈希及严格未完成边界；不直接编辑生成文件 |

README、ARCHITECTURE、docs 总索引、契约及其索引已能正确区分离线工具、生产输入和质量边界，
本轮核对后不再追加同义机制说明。根规则保持精简，未向其中写入单次流程叙事。
`CHANGELOG.md` 在本项目明确为 ignored local-only，收尾证据放在既有 `docs/reviews/` 并加入档案索引。

## 验证与受控警告

- 只读盘点机械枚举 Markdown 和规则路径。原始 465 个 Markdown 包含嵌套的既有 worktree 副本；
  文档门禁按主 checkout 的适用范围核验，不把机械枚举误称为逐篇审读其他 worktree。
- 重跑 F04 专项、profile/replay/benchmark、numeric/F02/reference 与接力隔离测试：
  **154 passed**，保留 1 条既有 Starlette/httpx deprecation warning。
- F04 机器报告哈希与验收文档相符，20 份原 prompt 哈希及还原 JSON 哈希一致，
  解码后 inventory 保留率均为 1，19 项候选采用、1 项 `nonbeneficial`；收益仍只是字节对照。
- 本机 10 项技能格式校验与显式技能依赖解析通过；Codex 当前技能目录已包含 `writing-plans`。
  本轮只读核对安装状态，未改技能或扩大全局配置。
- 包／CLI 及相关脚本、测试 Ruff、文档索引与链接检查、`git diff --check` 通过。
  未重跑曾受本地代理影响的全量 pytest，不能声称整个仓库基线通过；未改变代理设置。
- 静态首页一致只能证明静态入口，不能证明 Reader 的 Python 代码已经重载或真实模型服从度。
  没有重启服务，也没有重建或删除既有前端资产。

## 清场预览：现场保留

以下是本会话此前生成的两份旧比较临时副本，最终合并机器报告已保留对应运行和更完整的校验字段：

| 删除候选 | 当前字节 | 原因 |
| --- | ---: | --- |
| `/tmp/f04-ningde-implemented-comparison.json` | 12,098 | 被 F04 最终合并对照报告取代的中间版本 |
| `/tmp/f04-jianghuai-implemented-comparison.json` | 13,360 | 同上，含未派发保存修复的最终证据已保留 |

以下三份临时文件可能含独有的详细测量清单，本次保留，不纳入上述删除建议：
`/tmp/f04-ningde-input-profile.json`、`/tmp/f04-jianghuai-input-profile.json`、
`/tmp/f04-synthetic-required-inventory.json`。
本次审计的盘点文本和起始文件哈希快照也留在临时目录供复核。

已完成计划、测试夹具、可复用诊断脚本及机器报告仍有追溯或回归用途，不作为“残留”删除。
既有 worktree、分支与用户 `~/.tradingagents/` 数据均未触碰。
**复核现场仍保留，等待用户确认后清场。** 未取得本汇报之后的明确确认前，不执行上述删除。

终态为本地知识面已对齐并验证，保留上述 `pending`／`out-of-scope` 和 warning；
不代表 `merged`、`deployed`、`live verified`、全局知识页已刷新或 `cleaned`。
