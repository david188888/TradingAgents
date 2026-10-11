# ChatGPT 订阅接入实施计划

Status: Historical

Do not use this document as evidence of current implementation behavior.
现役配置与边界见 [订阅配置](../../operations/chatgpt-subscription.md)，
此页保留实现过程和当时验收证据。

依据：[已批准设计](../specs/2026-10-10-chatgpt-subscription-design.md)。

用户目标：在本地工作台登录 ChatGPT，并自由选择账户的动态模型目录，使用
计划额度完成现有研究。默认供应商和已有 Reader 修改保留。

| 任务 | 依赖 | 验收条件 | 估点 |
| --- | --- | --- | --- |
| 受保护的 OAuth 注册与账户管理 | 官方协议 | 身份验签、PKCE/state/nonce、授权状态、串行刷新、退出与取消均有离线验证 | 8 |
| 动态目录与 Responses 客户端 | 注册服务 | 未来模型能进入目录；零推理重试；仅 completed 返回；silent stream 可取消 | 5 |
| 单次、批量及恢复接线 | 账户、客户端 | account_ref 冻结；不会转计费或账户；模型失败持久化且不触发 repair | 5 |
| Web 控件与状态 | Web 契约 | 登录、切换、刷新、过期选择和额度恢复；两个表单一致 | 5 |
| 文档与验收 | 全部接线 | scoped pytest/Vitest、Ruff、typecheck/build、浏览器检查；真实调用等待用户登录 | 3 |

实施顺序按依赖执行。测试使用临时凭据和模拟 HTTP，不读取现有 Codex 登录；
运行配置仅保存 opaque account_ref 与模型 slug，认证对象通过 factory 注入。
范围不包括代理、账户池、质量比较或 GitHub 发布。

## 本地实现与验证

OAuth、目录、Responses、原生运行、单次/批量控件及安全诊断已接线。
目录方法与注册服务同属 `chatgpt_auth.py`；凭据不进入模型选择 API 或运行配置。
Ruff、文档链接检查、前端类型检查与生成资产构建通过。
已有 Reader 的未提交改动保留，生成 SPA 自然包含这些改动。

验证使用临时 auth/run 目录、模拟 JWKS/HTTP/SSE，未使用真实账户或额度。
范围内 Python 回归通过；前端 Vitest 与整个 Playwright 工作台回归通过。
新测试还覆盖 OAuth 身份/同意/过期/回调、跨进程旋转退出、账户绑定、
未完成流、静默流取消/截止/退出、刷新中取消、quota 无重试及主调用/repair 用量分离。

确认没有活动研究后，已重启本地 8000 工作台并验证订阅控件。
真实授权首次被拒绝，原因是初版主机 ID 使用裸 hex；已改为官方支持的
UUIDv4 URN 并补充跨重启稳定性与不改写账户绑定的回归测试。
用户完成身份验证和授权后，已确认账户的计划使用权限，以及两个模型选择器
中的 7 个真实目录选项。目录保留官方顺序：GPT-6.1-Sol、GPT-6-Astra、
GPT-6-Sol、GPT-6-Luna、GPT-5.6-Sol、GPT-5.6-Terra、GPT-5.6-Luna。
真实流的终止快照 `output` 为空，但 `response.output_item.done` 携带完整文本；
已修复收集逻辑，仍需 `response.completed` 才接受输出，并关闭异步流迭代器。
修复后 GPT-6.1-Sol 最小调用返回 `OK`，官方报告输入 17、输出 5，共 22 tokens。
该次复验只有一次推理请求；之前的一次客户端检查和一次有界协议诊断也实际
发送了最小请求，没有自动重试。未启动完整公司研究，剩余订阅额度和货币成本
没有推断或显示。
没有 GitHub 发布。

本轮验证记录：Python 范围回归 650 passed；后续 OAuth/原生诊断联合检查 67 passed。
Vitest 全量 335 passed，后续目录保留字用例在 4 项聚焦测试中通过；
Playwright 全量 24 passed，最终构建后的订阅配置 2 项复验通过。
真实服务使用的 Python 环境中，最终订阅/原生模型/诊断检查 73 passed；
真实 loopback 回调测试明确绕过环境代理。Ruff、文档检查和 diff 检查通过。
随后真实流修复的终止确认、输出顺序及异步迭代器清理回归已验证：
订阅/原生模型/诊断联合检查 77 passed。
真实流修复已加载到 8000 工作台；重启后账户授权和 7 项目录仍有效。
