简体中文 | [English](README.en.md)

# TradingAgents

面向中国 A 股的本地多 Agent 研究工作台，源自 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)。它把公司资料、公告、财务和行情组织成可复核的研究记录，帮助研究者看清**关键依据、主要疑点和下一步需要验证什么**。

新建研究统一判断公司的投资吸引力，综合经营、当前估值、事件与市场风险，给出理由、反证与改变判断的条件；支持批量公司研究，历史催化与持仓记录仍可读取和恢复。持续维护的入口是 Web 工作台；系统不生成订单或目标仓位，也不构成投资建议。

[![观看 TradingAgents 24 秒演示](https://david188888.github.io/images/tradingagents-demo-poster-20261008.jpg)](https://david188888.github.io/videos/tradingagents-demo-20261008.mp4)

24 秒演示：英文旁白与字幕，展示保存的历史研究样例（2026-10-06）；点击封面播放。

## 项目亮点

- **A 股证据链**：整合公开公司资料、官方披露、财务与行情，保留来源、时点和覆盖限制。
- **有分工的多 Agent 研究**：经营、事件、市场专项独立形成假设，经一轮质疑、实际核查与被质疑专项回应，再形成综合判断；代码负责证据资格、引用校验与确定性计算。
- **可追溯的研究阅读**：研究进行中即可查看各环节通过校验的保存产物、事实与来源，阶段提议与最终结论明确区分；Reader 与 Markdown 使用同一保存记录，阅读不重新取数或调用模型。
- **公司报告持续交付**：公开介绍、基本面与行情独立保留；资料缺口限制对应章节，综合未完成时交付已有基础报告与有效专项汇总，并明确暂未形成总体评级。
- **数值片段可核查**：新建研究引用冻结数值，由代码生成带单位、期次及实际／预测属性的片段，并校验到 Reader 与导出；外围解释仍需研究者复核。详见[数值合同](docs/contracts/numeric-narrative.md)。
- **通俗阅读**：财务与历史风险指标附带释义，百分比和金额统一整理；新研究完成后补充独立保存的模型通俗版，正文与相关依据共用，专业原文可展开核对。历史报告只改善指标解释与数值展示。详见[阅读边界](docs/contracts/report-explanation.md)。

## 整体架构与 Agent 设计

```mermaid
flowchart LR
    A[公开数据源] --> B[资格校验与证据冻结]
    B --> C[证据研究内核]
    C --> D[本地运行与研究记录]
    D --> E[Web Reader 与 Markdown]
```

| 角色／层 | 职责 |
| --- | --- |
| 经营、事件、市场专项 Agent | 使用各自的证据视图提出假设与失效条件，互不读取其它专项草稿。 |
| 独立挑战 Agent | 寻找反证、证据缺口与需要核查的条件。 |
| 被质疑专项 Agent | 依据限定事实回应一次，可维持、修正、撤回或承认无法回答。 |
| 综合 Agent | 综合证据、反证与回应，形成投资倾向、理由、失效条件和四维判断。 |
| 代码宿主 | 控制数据准入与运行边界，核查可计算条件，校验并保存研究结果。 |

基础研究先独立完成并保存，再按需回应用户关注点；补充回应不能改写基础结论。完整执行、恢复和模块边界见[系统架构](ARCHITECTURE.md)。

## 快速开始

需要 Python 3.10+。模型可使用所选供应商的 API Key，或通过官方登录授权使用 ChatGPT 订阅额度。默认模型为 DeepSeek V4.1 Flash（`deepseek-flash`）。

```bash
git clone https://github.com/david188888/TradingAgents.git
cd TradingAgents
# 已有 tradingagents Conda 环境时直接复用。
# 仅首次且环境不存在时：conda create -n tradingagents python=3.13
conda activate tradingagents
python -m pip install -e ".[china,web]" --index-url https://pypi.org/simple

cp .env.example .env
# 在 .env 中填写 DEEPSEEK_API_KEY；也可启动后选择 ChatGPT 订阅并登录。

tradingagents web --port 8765 --open
```

安装命令显式使用官方 PyPI，避免镜像访问异常。默认 A 股安装不包含与 Web 依赖冲突的 mootdx；既有环境修复与通达信补充能力见 [A 股数据能力](docs/operations/a-share-data-capabilities.md)。

订阅登录后，模型列表随账户官方目录更新；权限和额度由官方服务确认。详见 [ChatGPT 订阅配置](docs/operations/chatgpt-subscription.md)。
新建 ChatGPT 研究支持显式推理投入配置，并保持历史恢复的原请求语义；登录刷新具备按账户的暂时故障退避。

Web 仅绑定 `127.0.0.1`，自带前端，运行时无需 Node.js；运行记录保存在 `~/.tradingagents/`。凭据仅放在被 Git 忽略的本地配置中。数据权限与配置见 [.env.example](.env.example) 和 [Web 操作说明](docs/operations/evidence-research.md)。

## 当前限制

- **覆盖有限**：公开来源可能缺失、限流或无法验证历史时点；部分历史估值能力依赖 Tushare 凭据和权限。交易日历已改为由指数行情本地派生，不再依赖有每日配额的供应商。
- **研究质量仍需验证**：运行完成可能仍是 `partial / LOW_CONFIDENCE`；证据核查通过不代表经济原因或合理价值已确定，也未证明预测准确率提升。
- **产品范围明确**：当前维护本地 A 股 Web 研究；CLI 分析不再维护，旧流程保留历史读取与兼容恢复。

## 深入了解

| 想了解什么 | 文档入口 |
| --- | --- |
| 整体架构、模块职责与 Agent 边界 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 运行、数据源、模型与恢复 | [Web 操作](docs/operations/evidence-research.md) · [模型配置](docs/operations/llm-reasoning.md) |
| 研究记录与证据契约 | [契约索引](docs/contracts/README.md) · [研究记录](docs/contracts/research-record.md) |
| Reader 的证据追溯与展示 | [Reader 架构](docs/architecture/research-reader.md) |
| 编码 Agent 与贡献者如何修改项目 | [AGENTS.md](AGENTS.md) · [CONTRIBUTING.md](CONTRIBUTING.md) |
| 全部文档与发布记录 | [文档索引](docs/README.md) · [3.5.0 发布说明](docs/reviews/2026-10-16-v3.5.0-release-notes.md) |

编码 Agent 从 [AGENTS.md](AGENTS.md) 开始；当前行为以代码、契约和当前状态文档为准，历史计划不是实现证据。


## 致谢与许可

感谢 [TauricResearch](https://github.com/TauricResearch/TradingAgents) 的多 Agent 框架、[Simon Lin](https://github.com/simonlin1212/a-stock-data) 的 A 股数据参考，以及数据服务与开源库维护者。本 fork 在上游基础上发展了上述证据研究与本地工作台设计。许可见 [LICENSE](LICENSE)。
