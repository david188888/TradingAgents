# ChatGPT 订阅接入与动态模型选择

Status: Reviewed — 官方直连方向已获用户确认；独立设计审查通过，等待用户书面设计审阅。
Date: 2026-10-10

## 1. 目标与已确认需求

TradingAgents 的本地 Web 工作台新增「ChatGPT 订阅」模型供应商。用户通过
OpenAI 官方 Sign in with ChatGPT（SIWC）授权后，用自己的 ChatGPT 计划额度
完成现有证据研究，不需要填写 OpenAI API Key 或运行额外代理。

用户已确认官方 OAuth 直连路线，并要求自由选择模型：不能只提供
GPT-6.1 Sol，也不能依赖代码中写死的“最新版本”。所有账户目录中可展示的
模型都进入选择器；官方新增模型可通过刷新出现。

成功条件：登录 → 拉取真实账户模型目录 → 选择模型 → 完成一次模型调用 →
在现有研究流程中保存合法结果。目录中有模型只证明它可展示；一次调用的
权限、能力和额度，以该次推理的实际终态为准。

## 2. 第一性原理与范围

模型名称、身份授权、调用协议、额度归属是不同的契约。新增一个模型 ID
不能把 API Key 计费变成订阅计费，也不能证明账户有权使用该模型。

本方案增加认证管理、动态目录和专用模型客户端，以及它们在配置、运行、
恢复和界面中的必要接线。维持现有证据收集、Agent 顺序、引用校验和结果
门禁；DeepSeek 与其它 API 供应商仍可手动选择，默认供应商保持现状。

不引入代理服务器、Codex app-server、账户池、自动账户轮换、托管工具或
自动切换计费路径。旧 classic/catalyst 仅保留已有读取与恢复能力；新增
ChatGPT 订阅仅供维护中的 `evidence_v1` Web 单次与批量研究使用。

## 3. 当前代码的接入点

- `tradingagents/web/api.py`：`/api/config` 当前按 API Key 环境变量构造
  provider 列表，`_analysis_request` 按静态目录验证模型。两处都要支持
  OAuth 配置状态、动态目录及账户绑定，不能以“无需 Key”等同于已登录。
- `frontend/src/hooks/useConfig.ts`、`Controls.tsx`、`BatchControls.tsx`：
  目前供应商选择重置 quick/deep 模型。新增刷新与登录状态，保留仍有效的
  用户选择；单次与批量共用同一认证组件和目录行为。
- `tradingagents/llm_clients/factory.py`：增加独立的 `chatgpt` 分派。
  现有 `OpenAIClient` 有静态模型能力判断和 API Key 行为，不直接复用其
  请求构造来发送订阅请求。
- `tradingagents/execution/native_model.py`：维护中的内核发送文本 prompt，
  接收 `.content` 后由 Pydantic 与证据规则校验。专用客户端可实现这一
  接口，不需要把图改成 Codex 对话或 function tools。
- 当前 native 调用会把异常统一改写为 `NativeModelUnavailable`。需要
  保留经脱敏的订阅失败原因，同时维持已有预算和失败产物语义。

## 4. 组件边界

### 4.1 服务端认证管理

新增 `tradingagents/llm_clients/chatgpt_auth.py`，负责认证注册、凭据存储、
ID token 验证、账户选择、刷新和注销；不依赖 FastAPI 或研究领域模型。
通过构造参数注入凭据目录、时钟和 HTTP transport，测试使用临时目录。

运行依赖接线使用现有 runner_factory/caller_factory 扩展点：Web composition
创建单一 auth service，通过 SingleRunManager 的 runner_factory 构造带
订阅依赖的 NativeRunner，再由 caller_factory 给 NativeModelCaller 注入
认证 resolver；`_invoke` 仅在 chatgpt 分支把 resolver 和取消/deadline
回调传给专用客户端。自定义 manager 必须显式使用同一 resolver，不匹配
则 startup 报错。依赖对象不放进 effective_config，不依赖进程全局当前
账户，测试中的多个应用/临时凭据目录也不能互相泄漏。

生产凭据存放在 `~/.tradingagents/auth/chatgpt/`，目录权限 `0700`、文件
`0600`，原子替换。保存主机的稳定 opaque host ID、账户注册 ID、已验证
身份、issued client ID、令牌和过期信息。凭据文件不进入 run store、
effective_config、checkpoint、浏览器存储、版本库和日志。服务端为账户
生成稳定、不含邮箱或 token 的 `account_ref`，供界面选择及运行绑定。

同一邮箱的不同注册分别保存。界面可选择已保存账户、添加账户或注销，
不做池化调用。令牌刷新按注册串行，使用跨进程文件锁，拿到锁后重读最新
令牌；替换 refresh token 时不与另一个刷新并发。

### 4.2 官方登录流程

1. 用户点击 `Continue with ChatGPT`；本地 Web 发起一次登录请求。
2. 独立回调 listener 只绑定 `127.0.0.1`，使用可用端口和固定
   `/auth/callback` 路径；先监听，再打开授权页。每次生成随机 state、
   nonce 和 PKCE S256；登录尝试只在内存保存，十分钟后过期。
3. 首次用 `dynamic_agent_client` 和 `agent_name_hint=TradingAgents`，
   带本机 host ID；已注册账户复用 issued client ID。请求官方身份与
   计划使用 scopes：`openid profile email offline_access resource.invoke
   chatgpt.tokens.use.direct`，resource 固定为 `https://api.openai.com/v1`。
4. 回调校验 state，只消费一次；拒绝授权、超时、重复回调和返回 client
   ID 不匹配均不替换已有账户。新注册必须拿到 issued client ID。
5. 使用相同 redirect URI 和 PKCE verifier 换 token；按 OpenAI discovery
   与 JWKS 验证签名、issuer、audience、expiry、nonce 和 granted scopes。
   不接受仅解码 JWT、不验签的实现。
   已保存注册的重新登录必须与原已验证 issuer/sub、issued client ID
   一致；不同身份不能覆盖该注册，须重新走添加账户流程。
6. 身份校验成功但未获得 direct-use scopes 时保存「已登录，计划授权未
   启用」状态，不设为可调用；允许用户主动补充授权，不循环发起 consent。
   不完整/无效的身份验证则完全不保存新凭据。
7. 校验成功后原子保存注册，将其设为当前界面账户，关闭 listener。回调
   只展示完成状态，不回传 token。前端轮询有界登录状态，成功后刷新目录。

授权页使用官方 HTTPS 地址；token exchange、refresh、discovery、JWKS
只访问已验证的官方 HTTPS endpoints，拒绝跨站重定向。OAuth URL、回调
query 和请求 Authorization 不写 access log；listener 不使用默认 query
日志。新开页面的 opener 隔离；敏感状态响应 `Cache-Control: no-store`。

登录管理 POST 只接受本地工作台 same-origin JSON 请求，校验 Origin/Host
并保留 Web loopback 边界；OAuth 回调是单独的 state/PKCE 验证入口，不
套用禁止跨站导航的规则。取消/过期关闭尝试，不清除其它账户。

### 4.3 动态模型目录

新增 `chatgpt_catalog.py`，使用所选注册的 access token 请求官方
`GET /v1/models`。解析 `models` 数组，展示 `visibility == "list"` 的
全部条目，保留服务端顺序、`display_name` 和精确 `slug`，不按 GPT 前缀、
版本号或当前静态白名单过滤。quick/deep 两个选择器都使用这份完整列表。

目录按 `account_ref` 缓存五分钟，显示更新时间；登录、账户切换以及用户
点击「刷新模型」强制更新。后台响应带 account_ref，前端忽略已切换账户
或被更新请求取代的迟到响应。刷新保留仍存在的选项；消失的已选模型显示
失效状态并阻止新建，不静默替换。初次没有选择时用官方列表首项，不声称
首项一定是发布日期最新的模型；明确展示官方推荐顺序。

首次拉取失败或返回空列表时显示原因，不借用其它账户或静态 GPT 列表。
同账户过期缓存可继续展示并标为过期，但新建前必须完成目录再校验；失败
阻止新建。不逐个发付费/额度推理请求，不对“可展示”宣传为“已验证可用”。
官方目录中的新模型通过列表刷新即可选择，不提供订阅的任意自定义 ID。

### 4.4 订阅专用客户端

新增 `chatgpt_client.py`，实现 `BaseLLMClient` 的 factory 接口，返回支持
`invoke(prompt)` 的 LangChain Runnable，结果为 `AIMessage(content=...)`。
维护中的研究无需 tools，因此首版请求只包含显式 model、文本 input、
`store=false`、`stream=true`；固定 `https://api.openai.com/v1/responses`。

令牌由冻结的 account_ref 解析，不读取 `OPENAI_API_KEY`、Codex auth 文件
或代理配置。拒绝为该 provider 覆盖 backend_url。不传继承自其它供应商
的 temperature、max_tokens、max_output_tokens 等不支持字段。初版订阅
provider 使用模型官方默认 reasoning effort，不把 DeepSeek high/low
策略套用到未知模型，也不为新模型猜测支持的 effort；自由选模型不要求
新增推理档位界面。

SDK/network 推理 retries 为零，一次 invoke 至多一个 Responses 请求。
在推理前刷新需要的令牌；认证、目录请求有独立短超时，并计入剩余运行
时间。订阅调用仍须遵守 native 的 durable dispatch 和 global slot。
取消检查传入客户端，在流消费中检查剩余总时间和取消状态，退出时关闭
连接；独立 watchdog 监视取消和绝对截止时间，能够终止没有新 SSE 事件
的阻塞读取。使用可取消的 HTTP transport，不能仅在收到 delta 后检查。
SDK socket timeout 不能替代总截止时间。

收到文本 delta 暂存，但仅在 `response.completed` 后返回完整文本；
`response.failed`、`response.incomplete`、显式 error、EOF、超时和取消
都不能提交部分 JSON 为有效模型结果。usage 存在才记录真实 tokens；
缺失保持 unknown，不把订阅请求换算为 API 美元成本。

## 5. Web 契约与运行绑定

在 `web/` 新增薄认证路由与 schemas；`create_app` 注入认证服务。计划端点：

| Endpoint | 行为 |
| --- | --- |
| `GET /api/chatgpt/status` | 脱敏账户列表、当前选择、登录状态和管理用量链接 |
| `POST /api/chatgpt/login` | 创建登录尝试；返回安全授权 URL 与随机 attempt ID |
| `GET /api/chatgpt/login/{attempt_id}` | 读取 pending/complete/failed/expired 状态 |
| `POST /api/chatgpt/login/{attempt_id}/cancel` | 关闭该未完成尝试 |
| `POST /api/chatgpt/account` | 切换界面当前 account_ref，不修改运行 |
| `POST /api/chatgpt/logout` | 停止该账户的新请求并撤销 renewable session |
| `POST /api/chatgpt/usage/retry` | 用户主动解除该账户的本地额度暂停，不发推理请求 |
| `GET /api/chatgpt/models` | 所选账户目录；显式 refresh 参数可强制更新 |

`/api/config` 添加 `chatgpt` provider，认证类型 `oauth`，不要求 API Key；
`configured` 取决于已验证账户和计划授权。该常用入口只读本地状态，不
等待远端模型网络请求；动态目录由专用端点提供。现有 provider 的结构与
配置状态保持兼容，新增字段有明确默认值。

单次与批量 RunCreateRequest 增加可选 `chatgpt_account_ref`：chatgpt 时
必填且必须指向已验证、未注销的注册，其它 provider 携带它则拒绝。新建
前用该注册的近期目录验证 quick/deep slug，不用可变的“当前账户”代替。
neutral effective_config 只冻结 account_ref、provider 和模型 IDs；
身份、邮箱、token、过期时间及 host ID 均不进入运行语义配置。

批量入口的 owning schema 是 `BatchRunConfigRequest`，同样增加可选
account_ref 和 provider 条件校验；`/api/batches` 手工构造每个
RunCreateRequest 时显式转发该字段。批量 DTO、TypeScript contracts 和
buildRequestForTicker 均须覆盖这一传递，不只修改单次 RunCreateRequest。

批量创建时冻结同一注册和模型，不在后续调度时重读 UI 当前选择。恢复
保留冻结注册与模型；令牌续期不改变运行 identity，账户切换不改变已有
运行；缺失/注销注册时明确失败，不借用另一个账户。已经 dispatch 且
结果未知的请求维持现有恢复约束，不能凭重新登录重复发出。

每个注册维护 session generation；重新登录/注销改变它，正常 token 轮换
只改变 token version，不使已有调用变成另一个会话。跨进程注册锁覆盖
refresh HTTP 请求和原子提交的完整周期；等待锁也受剩余 deadline 约束。
注销取得同一锁后先禁止调用并变更 generation，再捕获/撤销最新 refresh
token。因此必须等到进行中的旋转刷新提交后才撤销，不能只检查 generation
并丢弃迟到的 replacement token。网络超时保持已禁用状态和待撤销记录。
注销也取消该注册未完成的重新登录尝试；迟到授权结果不重新激活该注册，
若已经拿到新的 refresh token，先保存待撤销记录并尝试 revoke。换账户只
修改 UI 选择，不变更其它注册会话。

注销先禁止该注册后续调用并尝试官方 revoke。网络/5xx 保留必要的待撤销
凭据、在有界窗口重试；若完成本地退出却未确认远端撤销，明确说明并给
ChatGPT 设置入口。单次 revoke 超时最多十秒，整个撤销窗口最多三十秒；
窗口结束完成本地退出时清除该注册 access/refresh/id tokens 与待撤销
token，仅保留「远端撤销未确认」的非凭据状态，不永久保存待撤销凭据。
迟到登录 exchange 获得的 token 使用独立同样有界的撤销流程，完成后
也清除；界面不能声称远端已撤销。原注册映射和主机 ID 保留；账户其它注册不受影响。
正在进行的 wire request 可能已经消耗额度；取消本地调用并拒绝后续阶段，
不宣称能退回额度。

## 6. 错误、预算与前端体验

订阅异常包含脱敏的分类、upstream status、稳定 error code、request ID
和建议动作。新增 neutral `ModelFailureDiagnostic` schema，字段为 stage、
category、upstream_status、upstream_code、request_id、safe_message、action；
upstream_code 可空，action 只允许 sign_in/manage_usage/refresh_models/
retry_later/check_permissions/check_capability/cancelled。只保存经过字段
筛选的诊断，不把完整 HTTP 响应体/异常 repr
或授权信息写入审计。没有机器 code 的 `{detail: ...}` admission 错误
不臆造 OpenAI code；保留 status，展示经限制长度与脱敏的说明。

具体持久化路径：NativeModelCaller 在 `_invoke` 捕获订阅异常后，把 schema
校验后的诊断写入 durable journal 的 `native.model_failures`（按 stage
保存），然后抛出带 safe diagnostic 的 NativeModelUnavailable 子类。
graph/native_research 的 `_call` 与 native_focus 的异常分支保持既有降级
状态，并保留该诊断，不把它覆盖为通用失败字符串。该 journal 记录随
checkpoint/event 持久化；ReaderProcessDTO 新增可选 `model_failures`
数组，由只读 process projection 重建并经 schema 验证，前端独立的
ModelFailureNotice 展示错误与动作。旧记录缺该字段时为 []，不推断成功。
不把模型错误混入数据 `source_failures`，也不改写基础研究结论。

成功调用的 usage 在 NativeModelCaller 保存到按 stage 的 journal 记录，
由 `_call` 的 main settle 使用；repair settle 继续读取 AIMessage 的
usage_metadata。只有 input/output 都是已测量非负整数时计为可用；错误
终态的已知 usage 如实保留，但不据此提交有效产物。

额度超限停止该账户后续订阅请求，提示「管理用量」；不推测重置时间或
整个计划均已耗尽。这个暂停状态保存到注册的非令牌状态，并在 status 中
显示；它不修改模型目录或注销凭据。用户管理用量后可主动点击「重新尝试」，
经受 same-origin 保护的 usage/retry 清除本地暂停，不自动发推理；之后
显式发起新研究才使用额度。再次 quota 错误重新暂停。不靠推测的计时器
自动恢复，不重放原运行已 dispatch 的失败/未知阶段。未获资格/权限、地区限制和不支持能力不重复请求；
已撤销/终止刷新失败提示重新登录。临时不可用保留凭据并提示稍后重试，
不在研究中做透明重试、换模型、换账户或换计费。错误通过 native 调用层
传递并进入已有失败/降级产物，结构修复只针对输出校验失败，不能用于
重试 quota/auth/protocol/transport 错误。并行阶段已发出的调用无法撤销
额度，未发出的阶段在检查账户受限状态后停止。

基础研究调用失败继续使用既有 unknown/partial 门禁；可选 focus 失败
继续保留已保存基础研究，展示其具体失败原因。调用次数、deadline、
repair 次数和历史恢复边界不扩大。订阅路由无法指定 max_output_tokens，
所以不宣称能强制固定输出 token 上限；依然用 prompt、流截止、现有
调用预算和结果校验约束执行。

界面在 provider 附近显示「使用 ChatGPT 订阅」、当前账户、登录/退出、
模型更新时间、刷新和管理用量入口。首次授权完成后说明请求使用计划
额度，之后不反复弹出。用量金额、剩余百分比和重置时间只有官方可验证
数据时才显示；首版用量入口以官方 Usage 页面为准。官方是否允许用额外
credits 由用户在 ChatGPT 设置管理，本项目不操作余额或购买。

## 7. 验证与交付

离线测试使用临时 auth 目录、固定时钟、模拟 JWKS 和 HTTP/SSE transport，
禁止访问真实账户或使用本机已有凭据。至少覆盖：

- OAuth 成功；错误 state/nonce/audience/signature/scopes/client ID；
  授权拒绝、过期、重复 callback、取消和 listener 释放。
- 文件权限、原子写、跨进程旋转刷新、注销、令牌字段与 URL 日志脱敏。
  特别验证 refresh R1→R2 正在进行时 logout 等待并撤销 R2，以及迟到
  的重新登录 replacement token 不被遗弃、不重新激活注册。
- 未来未知模型进入列表、官方排序、同邮箱不同注册隔离、空目录、过期
  缓存、切换账户后的迟到响应、刷新不替换选择、新建再校验。
- 精确 Responses endpoint、stream/store 字段与禁止参数；终态成功、
  delta 后失败、incomplete、EOF、取消、总超时和零推理重试。
- 未登录不能新建；单次/批量冻结注册；token 轮换不改变 checkpoint，
  缺失注册不得换账户；quota/auth 失败不触发 repair 或计费回退。
  quota 暂停只能由用户显式解除，解除不发推理、不重放旧阶段，下一次
  新研究仍超额则重新暂停。
- UI 登录状态、目录加载/刷新/错误、两类表单一致，旧 provider 回归。

执行 agent-doc 检查、适用 Ruff/pytest、frontend install/typecheck/Vitest/
build 和相关 Playwright；frontend 变更包含生成资产。更新架构、模型
操作文档、文档索引与中英文 README 中的启动凭据说明。

离线通过后，由用户在官方页面完成登录，先做一条最小文本推理，确认
`response.completed`；再做一次有界单公司研究，核对 dispatch、持久化、
Reader 与失败语义。这会使用用户计划额度，不作批量性能/质量比较。
账户资格、该账户最新模型和真实额度可用性在这一阶段实测，无法由离线
测试或静态目录保证。用户输入登录信息留在官方页面。

保留本轮开始时已有 Reader 源码、样式、文档、测试和生成资产修改；
交付 diff 明确区分本功能文件，不能通过回滚或清理覆盖其它工作。

## 8. 资料与依据

官方资料于 2026-10-10 核对；本文是新增功能设计，不是已实现能力说明。

- [SIWC OSS overview](https://developers.openai.com/siwc/token-sharing-open-source)
- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)
- [UI/UX guidelines](https://developers.openai.com/siwc/ui-ux-guidelines)

历史约束参考 Hindsight 页「DeepSeek 单模型按任务配置推理投入」；当前
语义冻结、预算与运行接口以代码及 `docs/operations/llm-reasoning.md` 为准。

## 9. 设计审查记录

独立 reviewer 已审阅并给出 Approved。已修复令牌旋转与注销竞态，以及
额度暂停缺少主动恢复入口的问题；补齐原账户身份验证、未授权状态、
模型错误持久化、依赖注入、批量字段转发与无事件流取消的具体边界。
Agent 文档检查与 diff whitespace 检查通过。本阶段只新增设计文档，未
实施模型功能、执行真实 OAuth 或消耗账户计划额度。
