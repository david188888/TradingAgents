# 研究流程画布与相邻详情验收

- **Status: Historical** — Do not use this document as evidence of current implementation behavior.
- 日期：2026-10-11。当前行为见 [Reader 架构](../architecture/research-reader.md)。
- 已确认设计：[A 的流程布局 + C 的画布视觉](../superpowers/specs/2026-10-11-research-flow-design.md)。

## 交付与边界

`ResearchFlow` 在未发布运行页面及已发布 Reader 的研究过程视图共用。共同证据、独立专项、汇合质疑、代码条件核查、V7 专项回应、综合、发布及请求的关注点有明确依赖分组。代码核查与发布共享一个角色、一次统计，不代表两个执行实例。未知版本保留兼容列表。

桌面详情相邻，窄容器详情在下方；键盘、重复选择、关闭返回焦点及证据对话框可用。运行角色和对应连接才有动画，终止、取消请求及 reduced motion 下停止。计数仅来自合格公开记录/DTO。

600418 最新失败显示三个专项已完成、提议已保存但本次未发布，挑战/回应/综合未到达；不再显示无限等待发布或声称最终报告存在。记录读取失败和已确认 `not_published` 区分，并提供只读重试。

回归发现 `useReaderFocus` 原先只接受 V6，导致 V7 页面停留在等待。现已接受 V6/V7，保留 run、sequence、workflow 身份校验；未改变补充回应的生成、发布或预算。新画布的小字对比度与详情说明颜色已通过 axe 检查。

核心条件引用校验及误导性的 `missing_configuration` 分类仍未改变。详见 [600418 最新失败定位](2026-10-11-600418-latest-failure.md)。本次没有重试用户研究、修改历史运行数据或调用付费模型。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| `npm --prefix frontend ci` | 完成，使用跟踪的 lockfile |
| `npm --prefix frontend run typecheck` | 通过 |
| `npm --prefix frontend run build` | 通过；生成 SPA 已更新 |
| Vitest 全量 | 50 文件、349 测试通过 |
| Playwright 全量 | 26 测试通过；真实 HTTP/SSE/保存边界 + 合成数据，无模型调用 |
| 新流程与相邻详情 axe | 零违规；包含文字对比度 |
| agent-doc check / Ruff / diff check | 通过 |

交互回归覆盖 1512×900、1280×650 和 390×844 的逐环节选择、重复点击、焦点及关闭；还验证了已发布提议 → 支撑事实 → 证据对话框 → 返回、概念说明、运行时动画和 reduced motion、版本回退、V6 focus、V7 focus 的身份校验、读取失败重试及跨运行保护。

实际浏览器只读核对：最新失败 `run_20261011T111547929814Z_c6acb6ac`、已发布 V6 历史记录 `run_20261010T152904821989Z_493630f9` 的长正文。1512px 与 390px 无页面横向溢出；失败记录活动动效数为零。实际服务加载最终资产 `index-BKa8NzVC.js` / `index-Dv2p4N8F.css`。

截图保存在本机 `/private/tmp/tradingagents-research-flow-desktop.jpg`、`/private/tmp/tradingagents-research-flow-mobile.jpg`、`/private/tmp/tradingagents-research-flow-published.jpg`；未把个人历史界面加入仓库 fixture。

测试环境补齐项目 Web extra 已声明的 PyJWT。macOS 沙箱不能启动 Chromium，浏览器测试经批准在沙箱外运行；隔离测试服务与用户 8000 端口分离。构建仍有大于 500 kB 的 bundle 提示，此次未调整加载架构。
