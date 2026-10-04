# DeepSeek 按任务 effort：实现与验收记录

Status: Historical

Do not use this document as evidence of current implementation behavior.
See the [documentation index](../../README.md).

验证日期：2026-10-04。基线：`f18f7b1`。
本文保留离线验证阶段与后续真实链路验收的结果；发布状态以 GitHub PR 为准。
当前配置行为见
[运行说明](../../operations/llm-reasoning.md)，设计见
[实施规格](../designs/2026-10-04-deepseek-task-effort-design.md)。

## 实现范围

- 可选 `deepseek_task_efforts`：有限任务键、严格 `low/high/max` 校验，覆盖
  native、classic、legacy catalyst 和六种辅助调用。
- 未指定任务继承全局档位；没有新增默认策略或改写用户 preset，默认仍为 `high`。
- CLI 全局 DeepSeek 参数及任务配置完整传递；后台摘要读取运行保存的配置与端点。
- classic 角色使用独立客户端；新闻辅助调用使用独立绑定。原生／旧催化流程在
  身份构建与来源采集前冻结配置，修复继承原档位，沿用原预算和恢复规则。
- 启用任务策略时，新闻深度复核缓存区分解析后的 effort。
- 衔接上一批官方 `deepseek-flash` 名称、能力声明和显式关闭思考兼容修复。

这些实现与检查验证接线和控制逻辑。没有真实模型质量、成本、延迟或投资效果对照；没有
自动升档、新增模型阶段、默认 profile 切换或前端选择器。
Yahoo／Alpha Vantage 修复继续按用户注释延期。

## 结果

| 检查 | 结果 |
| --- | --- |
| 任务配置、原生模型、CLI、摘要、指纹、原生／旧催化生产接线的定向检查 | 233 passed；1 条既有 Starlette 弃用警告 |
| 先前配置、聚类、新闻层和摘要兼容检查 | 108 passed |
| 全套非 smoke 回归，明确排除付费 DeepSeek live test | 3115 passed、16 failed、5 deselected、74 subtests passed；299.07 秒 |
| Ruff（生产 Python、CLI、修改测试） | 通过 |
| agent docs 与 whitespace | 通过 |

关键断言包括真实 SDK 构造的离线 payload（不 invoke）、全部任务的档位映射、
并行隔离、原生单次修复与缓存恢复、配置指纹不兼容判定、CLI 副本隔离、
冻结摘要端点／档位、无效冻结配置零 dispatch，以及低／高档深度缓存不混用。

## 失败项基线对照

从 `git archive HEAD` 导出未修改基线，在同一 conda 环境的可写临时目录
重跑全套失败的 16 项；另一个同权限目录覆盖本次修改，重跑相同 16 项。
两者均为 **15 failed、1 passed**，失败节点集合完全相同。
两次都确认 `tradingagents.__file__` 指向各自临时副本，避免误测 editable 安装。

| 失败原因 | 数量 | 涉及文件 |
| --- | --- | --- |
| 旧 graph 边断言尚未包含估值预取节点 | 3 | `test_a_share_supplement_prefetch.py`、`test_evidence_steward.py`、`test_market_price_prefetch.py` |
| 当前 conda 环境缺少 `pypdf` | 3 | `test_disclosure_documents.py` |
| 固定日期与当前日期的字符串不同 | 1 | `test_fundamentals_lookahead.py` |
| 旧 v2 状态／指纹 pin 尚未包含 `valuation_bundle` | 3 | `test_runtime_scaffold.py` |
| 旧方法论契约预期未包含 `risk_asymmetry` | 2 | `test_skills_registry.py` |
| sandbox 不允许写实际用户 Web 日志 | 3 | `web/test_web_cli.py` |

第 16 项 `TestLoadOhlcvNoPoison::test_empty_download_raises_and_does_not_cache`
只因 managed worktree 的 `tests/_tmp_cache` 无写权限而失败，在上述两个可写
临时副本中均通过。没有为通过检查写入用户日志、安装依赖、改动这些旧断言
或放宽 sandbox。**本次观察到的失败没有新增代码回归；全套仍未通过。**

完整回归命令：

```bash
PYTHON_DOTENV_DISABLED=1 conda run -n tradingagents python -m pytest \
  -m 'not smoke' \
  --deselect=tests/test_deepseek_reasoning.py::TestDeepSeekLiveStructuredOutput \
  -q --color=no -p no:randomly -p no:cacheprovider --tb=short
```

定向检查使用同样的 dotenv／cache／randomly 隔离参数，路径为：
`tests/test_task_effort.py`、`tests/test_native_model.py`、
`tests/test_cli_config_precedence.py`、`tests/web/test_debate_summary.py`、
`tests/web/test_fingerprint.py`、`tests/web/test_native_production_wiring.py`、
`tests/web/test_catalyst_production_wiring.py`。

## 真实链路与浏览器验收

同日使用隔离的 loopback 服务、临时数据目录、官方 DeepSeek API 和公开 A 股
来源，完成一次 `evidence_v1` 公司研究。验收过程没有改写用户本地配置或
默认策略；临时配置仅将 `native.market_context` 设为 `low`，其余阶段为 `high`。

- 实际 SDK 发出五次主分析请求，均使用 `deepseek-flash`；经营质量、事件、
  挑战、综合为 `high`，市场上下文为 `low`，均收到成功响应且无需结构修复。
- 持久化研究记录、Markdown 与冻结配置可读取；恢复身份校验通过。
  重复读取 Reader／view 没有增加模型请求。
- 完成状态与证据充分性分开：运行完成，但记录仍为 **partial / LOW_CONFIDENCE**。
  缺少合格估值与部分披露正文，不将这种结果记为充分研究或分析准确性通过。
- `browser-harness` 在真实 Chrome 验证历史重开同一记录、依据展开和原文读取；
  桌面及 390×844 视口无横向溢出。此项使用实际保存结果。
- `jev-ultrafast` 仅在无研究记录、无真实凭据的空白工作台验证批量模式切换：
  1 次点击、2 次决策、768 ms，CDP 独立确认输入界面。自动审批拒绝把真实
  研究页发送给外部 Jev 服务，因此没有执行该外发操作。

这不是 effort 档位的质量／成本／延迟对照实验；单案例链路成功也不证明投资
分析准确性提高。真实研究内容与原始验收输出保留在本地临时目录，不纳入公开仓库。

## 浏览器测试退役与保留

主干对照确认旧 `DecisionBrief` 完成页与默认 Companion 路由断言已经过时。
经用户明确批准，删除旧截图套件及其 11 张专属快照，移除退役页面、旧角色数、
旧 Inspector／Companion 默认入口断言；历史记录 fixture 保留兼容测试用途。
保留并适配生命周期、秘密隔离、Reader/Audit 无障碍、键盘焦点与 reduced-motion
检查，新增分析模式键盘选择检查，没有降低 WCAG 阈值或删除有效失败断言。

保留检查发现两个现役问题并修复：分析模式改为按钮组与 `aria-pressed`；
Audit 入口保存实际触发控件，Escape 退出后恢复其焦点。

| 最终检查 | 结果 |
| --- | --- |
| Playwright：当前 classic/catalyst 合成 fixture，经实际 HTTP/SSE/store 与构建 SPA | 18 passed，29.0 秒 |
| Vitest | 45 文件、327 passed |
| TypeScript 与前端构建 | 通过；生成资产随源码同步 |
| npm 生产依赖审计 | 0 vulnerabilities |

依赖安装仍报告 16 项开发依赖漏洞；Vite 保留大于 500 kB 的 chunk 警告。
没有修改 lockfile、自动升级依赖或放宽构建阈值。Python 全套既有失败仍按上文
基线对照保留，不将本次浏览器通过写成整个仓库全绿。
