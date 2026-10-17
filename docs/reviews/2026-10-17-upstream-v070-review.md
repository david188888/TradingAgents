# 上游 v0.7.0 选择性引入评估

Status: Historical

Do not use this document as evidence of current implementation behavior.

本文是 2026-10-17 的代码审查与离线复核快照，提出候选适配，不代表已实施或获准集成。
当前产品边界见 [Product Context](../context.md)、[架构](../../ARCHITECTURE.md) 与
[ChatGPT 操作说明](../operations/chatgpt-subscription.md)。本轮不改变业务行为。

后续用户决定（2026-10-17）：不需要 Release 安装包发布，排除对应流程和资源修复；同意其余
分流意见并继续 ChatGPT 参数传递、刷新韧性的适配。下文保留原评审建议，实施边界见
[适配设计](../superpowers/specs/2026-10-17-chatgpt-upstream-adaptation-design.md)。
这两项随后完成本地实现与离线回归，见[验收记录](2026-10-17-chatgpt-upstream-adaptation-validation.md)；尚未重启服务或发布。

## 结论与第一性原理

建议优先适配 **ChatGPT 显式推理投入的传递**、**令牌刷新韧性**；其次借鉴
**可验证的发布安装包**。其余变化按实际入口保留、暂缓或不引入，不整包合并上游。

目标是使研究者得到必要、准确、可复核的公司研究。一个上游变化只有满足以下条件之一，
并且不破坏现有约束，才有引入价值：减少错误或遗漏；使模型、数据与失败行为符合显式配置；
保证安装者得到同一份完整产品；降低恢复与复核成本。

必须保留的约束：A 股优先；Web 是维护入口；专项隔离、证据资格和数值校验由代码控制；
模型请求受已有额度、取消和截止时间约束；恢复使用冻结配置；Reader/导出读取保存记录；
不恢复交易结算或自动反思写入。新增功能数量和上游版本号都不是价值证明。

失败条件包括：配置被静默忽略；刷新临时失败被等同于授权失效；安装成功但必需资源缺失；
盘后证据被用于声称当日收盘前已经作出的判断；历史记录被新语义改写。

## 审查基线

- 本地：`main`，`22d4c3f4d2d0095239696cd3055d81edbb75e507`，包版本 `3.5.0`；开始时工作区干净。
- 上游：[v0.7.0 发布说明](https://github.com/TauricResearch/TradingAgents/releases/tag/v0.7.0)，
  GitHub API 的 `published_at=2026-10-16T21:38:46Z`，即北京时间 **2026-10-17 05:38:46**。
- 固定目标：`e8f5503e9b86d5c2710b0c76b1f686703968c9df`；本次获取的 `upstream/main` 与它相同。
- 上一版：`1394a3f72aa4393e1a98f51b382434c4b4c2d972`（v0.6.0）。
  两版之间共 **11 个提交，37 个文件，2180 行增加、185 行删除**，包含合并、版本与文档提交。
- 与本地共同祖先：`9dee508c44662702281a8dbaad1f7b42179b5ba7`。本地已有手工适配，
  共同祖先不能用于推断功能缺失。本轮重点是 v0.6.0 → v0.7.0，并非补审所有历史分叉。
- 通过独立远端发布引用读取代码，没有切换/合并当前分支；没有改写本地版本标签。

## 完整主题分流

按以下 **11 个评估主题**统计：`take 0 / adapt 4 / defer 3 / reject 4`。
分类是建议；`reject` 指不引入该实现或替换，不否定其解决的问题。

| 主题 / 上游提交 | 分类 | 本地影响与建议 |
| --- | --- | --- |
| ChatGPT 整体 OAuth / 通用凭据注册表，`071a6ce`、`69042d6`、`36479ae` | reject 整体替换 | 本地已有账户注册、官方直连、轮换锁、账户冻结、额度暂停、退出中止流与安全诊断。保留独立客户端，按缺口适配，避免用上游单账户文件替换。 |
| ChatGPT reasoning effort，`36479ae` | adapt，优先 | 本地配置构造器不对 chatgpt 传此项，客户端即使收到也不写入请求。补完整链路，未配置时仍不传；不能统一强制 high，也不能假定所有模型接受同一档位。 |
| OAuth 刷新时间与暂时故障处理，`69042d6` | adapt，优先 | 借鉴保存/判断 earliest_refresh_at、仍有效令牌在暂时故障时有限续用、刷新退避；保留每注册账户锁、轮换原子写入和失效/权限/额度的明确边界。 |
| 模型目录按 priority 重排与 supported_in_api 额外过滤，`69042d6` | reject 照搬 | 本地按官方 visibility/slug/display_name 合同保留服务端顺序。当前官方文档没有给出这项额外过滤合同；不因上游实现而改变用户可选模型。 |
| CLI login/logout、粘贴回调、Docker/脚本登录，`69042d6`、`bc55fe3` | defer | Web 已能登录。新增无界面入口须先有实际需求；如做，也应复用本地账户服务，不能另建凭据文件或恢复维护整个旧 CLI。 |
| 跨供应商 quick/deep 档位的 None 覆盖修复，`7142746` | defer | 本地无这套独立 provider 档位实现；现有两模型共用一个 provider。旧 CLI 有无条件覆盖，但当前不维护；不为这个修复新增跨供应商功能。 |
| 收益从决策日期之后首个收盘开始计量，`f5e3eae` | reject 恢复模块 | 本地 backtest/settlement/reflection 写入端已退役，仅保留旧记忆读取。保留“信息可知时间必须早于计量起点”原则；未来评估研究结果需另定版本化协议。 |
| 非终端不抓公告、启动不等待远端，`c3cdaeb` | adapt，低优先 | 旧 CLI 仍同步抓公告并可能要求按键；Web 启动不走这条路径。若清理兼容入口，最小方案是移除/限制旧调用，不必增加更新系统。 |
| 每日后台更新提示及自动推导升级命令，`c3cdaeb` | defer | 本地 3.5.0 与上游 0.7.0 不能直接比较。要做需按 fork 的仓库、发布和安装方式设计；不接入上游公告服务，也不自动安装。 |
| Release source archive / wheel，`c9be8b6` | adapt，次优先 | 本地尚无对应 workflow。借鉴标签/包版本核对、构建、包外导入验证；新增方法库/SPA/预设资源检查，以及适合本地 china,web extras 的验证。 |
| cryptography / packaging 与版本、示例依赖修改，`f802271`、`bc55fe3` | reject 机械同步 | 本地 Web 已使用 PyJWT[crypto] 和 packaging，版本线与依赖分组不同。新增依赖应跟随实际适配；不复制上游版本号、依赖或登录示例。 |

## 优先候选的证据与边界

### 1. ChatGPT effort：设置应实际生效

上游的 [factory.py](https://github.com/TauricResearch/TradingAgents/blob/e8f5503e9b86d5c2710b0c76b1f686703968c9df/tradingagents/llm_clients/factory.py)
将 chatgpt 加入 reasoning effort provider，
[OpenAI 适配器](https://github.com/TauricResearch/TradingAgents/blob/e8f5503e9b86d5c2710b0c76b1f686703968c9df/tradingagents/llm_clients/openai_client.py)
通过 SDK 编译到 Responses 请求。离线构造得到 `reasoning: {effort: high}`，没有发 HTTP。

本地 [provider_kwargs.py](../../tradingagents/llm_clients/provider_kwargs.py) 只在 provider=openai
时取 openai_reasoning_effort；[chatgpt_client.py](../../tradingagents/llm_clients/chatgpt_client.py)
的请求仅有 model/input/store/stream。用 MockTransport 注入完成事件，显式传入
reasoning_effort=high 后，捕获的真实客户端请求仍没有 reasoning。

建议沿现有请求构造器 → 原生/辅助调用 → ChatGPT HTTP 客户端打通显式配置，保存有效值并纳入
恢复身份。需要同时审查已有恢复指纹：不能让历史冻结运行突然开始发送过去未发送的参数。
继续由现有执行账本管理请求与修复；不增加模型阶段、不自动提升 effort、不改变默认模型。
接口传参正确不等于研究准确率提高，具体模型/账户是否接受档位还须单独验收。

### 2. 刷新韧性：区分令牌过期、授权失效与暂时故障

上游 [chatgpt_auth.py](https://github.com/TauricResearch/TradingAgents/blob/e8f5503e9b86d5c2710b0c76b1f686703968c9df/tradingagents/llm_clients/chatgpt_auth.py)
保存 earliest_refresh_at；在过期前考虑服务端最早刷新时间。临时故障时保留仍有效令牌，
限制一分钟内重复刷新。该一分钟是上游实现选择，不是已证明适合本地的统一参数。

本地 [ChatGPTAuth.access](../../tradingagents/llm_clients/chatgpt_auth.py) 在剩余 60 秒时刷新，
登录与轮换记录都未保存 earliest_refresh_at。离线注入 now=1000、expires_at=1050、
earliest_refresh_at=1040，本地发起一次刷新，上游不刷新；注入暂时超时且令牌未过期，
本地抛出错误，上游返回原令牌且下一次调用处于退避。

[官方 token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference)
列出 earliest_refresh_at；
[accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
要求串行轮换、保留最新凭据和账户隔离。上述对比证明代码差异，没有证明真实账户已遇到它。

适配应按注册账户管理退避，并考虑旧令牌能否覆盖剩余请求时间；过期令牌不能继续使用。
invalid_grant、身份不匹配、权限/额度错误继续走明确失败，不得回退旧令牌、API Key、其他账户
或模型。还应评估刷新返回 id_token 时的身份校验；上游有该检查，本地刷新路径未使用此字段。
如引入校验，必须先解决校验依赖失败时如何不丢失已经轮换的 refresh token，不能直接拼接调用。

### 3. 发布安装包：先证明资源完整

上游 [.github/workflows/release-assets.yml](https://github.com/TauricResearch/TradingAgents/blob/e8f5503e9b86d5c2710b0c76b1f686703968c9df/.github/workflows/release-assets.yml)
从明确 tag 构建并验证版本，在 checkout 外导入 wheel 后上传。
它不测试本 fork 的 SPA、方法库或 A 股 extras，不能原样作为验收。

在 `/private/tmp` 的本地 HEAD 独立归档副本执行 `python -m build --wheel --no-isolation`：

- 成功生成 tradingagents-3.5.0-py3-none-any.whl。
- 包中存在 Web index、2 个静态 asset、2 个 preset 文件与 CLI welcome。
- 仓库的 11 个 `tradingagents/skills/library/*/SKILL.md` 在 wheel 中全部缺失。
- 将 wheel 解压至独立目录，在该目录导入 SkillRegistry，加载 financial-statement-analyzer
  抛出 SkillValidationError；模块路径已核对来自 wheel，而非 checkout。

原因与 [pyproject.toml](../../pyproject.toml) 的 package-data 声明相符。
该方法库由 classic 分析师等兼容路径使用；本轮没有据此判定当前 native Web 主链失败。
这是新增发布流程前应修复的包完整性缺口，而不是上游 v0.7.0 引入的本地缺陷。
本轮只构建/解压，没有安装 wheel，没有创建新的虚拟环境，也没有发布资产。

## 不照搬的关键原因

- **模型目录**：上游测试将原始列表按 priority 重排；本地保留响应顺序。
  [官方模型文档](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
  明确保留服务端顺序并随账户更新。保留本地合同，不引入未经定义的排序/过滤。
- **回测时点**：修复把决定日的盘后信息与之后的入场价格分开，是正确的防前视原则。
  它没有让文本源归档、运行可重复或证明投资有效；上游报告也保留这些限制。
  本地历史风险统计是回看统计，不能因此整体后移一天。未来评估需明确证据截点、
  输出完成时间、交易日历、计量价格、基准和协议版本；不能覆盖旧结果或混合口径。
- **公告与升级**：已核对 cli.main 的路由，web 子命令不执行交互分析的公告获取。
  旧公告问题不等于 Web 每次启动都联网；直接采用上游更新比较还会混淆两个仓库的版本线。
- **已具备的能力**：官方固定 Responses 路由、隔离 OAuth 凭据、无 API Key 自动回退、
  stream=true/store=false、completed 后接受输出等已由本地代码和测试覆盖，不能重复算作新增收益。

## 检查结果与局限

使用既有 `/Users/david/miniconda3/envs/tradingagents`，禁用 dotenv，未读取用户凭据/运行数据。

```bash
PYTHON_DOTENV_DISABLED=1 /Users/david/miniconda3/envs/tradingagents/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_chatgpt_subscription.py tests/test_analysis_cutoff.py \
  tests/test_memory_log.py tests/test_memory_pointintime.py
```

结果：**92 passed**，另有一项 FastAPI/Starlette 测试依赖弃用警告。
这证明现有回归状态，不证明缺口已修复或真实账户/投资结果通过验收。

- 逐项对照 11 个提交主题和 37 个文件变化，阅读关键实现、依赖、文档及对应测试。
- 自建离线探针通过：显式 effort 丢失、刷新最早时间差异、临时刷新失败差异。
  上游比较抽取原函数/客户端类注入依赖，不运行上游完整图或接触凭据。
- 临时复核脚本/结果：`/private/tmp/tradingagents-v070-review-probes.py` 与同名 `.json`。
- 临时构建、构建日志与解压包：`/private/tmp/tradingagents-v070-wheel-review-mkzxffs2/`。
- 没有执行完整 pytest、上游完整测试、前端重建、真实 OAuth/付费推理、网络故障实测或安装环境验收。
- 本轮仅新增本评审与归档导航；没有实现候选适配、修改配置、重启服务、提交或推送。

## 实施前的具体取舍

首批建议只处理 ChatGPT effort 传递与刷新韧性，保持缺省和历史运行语义，先离线验证再决定
是否授权真实账户验证。第二批处理 package-data 与发布包流程。旧 CLI、更新提示、跨供应商
档位、无界面登录和研究结果计量均不属于首批。

评估阶段没有必须阻塞的未知事实；实施范围、支持的 effort 档位及是否执行真实账户验收
仍需用户选择。后续有行为变更时应单独形成设计、确认后再实施，不能把本评审当作实施批准。
