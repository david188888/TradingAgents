简体中文 | [English](README.en.md)

# TradingAgents

面向中国 A 股的本地多 Agent 研究工作台，源自 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)。它把公司资料、公告、财务和行情组织成可复核的研究记录，帮助研究者看清**关键依据、主要疑点和下一步需要验证什么**。

新建研究统一判断公司的投资吸引力，综合经营、当前估值、事件与市场风险，给出理由、反证与改变判断的条件；支持批量公司研究，历史催化与持仓记录仍可读取和恢复。持续维护的入口是 Web 工作台；系统不生成订单或目标仓位，也不构成投资建议。

[![观看 TradingAgents 24 秒演示](https://david188888.github.io/images/tradingagents-demo-poster-20261008.jpg)](https://david188888.github.io/videos/tradingagents-demo-20261008.mp4)

24 秒演示：英文旁白与字幕，展示保存的历史研究样例（2026-10-06）；点击封面播放。

## 项目亮点

- **A 股证据链**：整合公开公司资料、官方披露、财务与行情，保留来源、时点和覆盖限制。
- **有分工的多 Agent 研究**：经营、事件、市场专项独立提出 Insight，每条只需观点、证据引用、推理理由、反证或局限；经过一轮质疑与回应，由综合 Agent 权衡依据。程序管理数字、引用与有效版本。
- **当前资料与证据引用**：新研究采用当前可得资料；模型选择短证据编号和数值标记，程序解析到保存的来源与片段。未发现有效反证、未审阅和审阅失败分别记录。
- **双路联网补证**：新闻、行业、政策与竞争材料由 DeepSeek/Tavily 配合检索；身份和量化数据优先使用专用接口，失败后按缺失字段补搜。材料合格后才进入研究，分析中按缺口有限补证并复核相关判断。详见[双路搜索](docs/contracts/dual-search-research.md)。
- **可追溯的研究阅读**：研究进行中即可查看各环节通过校验的保存产物、事实与来源，阶段提议与最终结论明确区分；Reader 与 Markdown 使用同一保存记录，阅读不重新取数或调用模型。
- **公司报告持续交付**：基础资料和合格观点独立保留；坏条目只修复一次，不拖累同组观点。综合依据无效时暂不评级；缺少特定估值指标不再自动否决综合 Agent 的判断，但资料缺口必须明示。
- **数值片段可核查**：数字由程序计算和渲染，保留主体、单位、期间与来源。未绑定的数量不能作为通过核验的输出；引用和计算通过不等于经济推断已被证明。详见[研究合同](docs/contracts/research-record.md#insight-first-v9)。
- **通俗阅读**：新报告可生成独立保存的通俗解读，未覆盖或失败时保留原文；解读覆盖率不参与研究验收。历史报告保留原有指标解释。详见[阅读边界](docs/contracts/report-explanation.md)。

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
| 经营、事件、市场专项 Agent | 使用各自的证据视图提出四项 Insight，互不读取其它专项草稿。 |
| 独立挑战 Agent | 质疑判断、证据充分性和替代解释；如实记录未发现有效反证。 |
| 被质疑专项 Agent | 依据限定事实回应一次，可维持、修正、撤回或承认无法回答。 |
| 综合 Agent | 综合证据、反证与回应，判断证据是否充分，形成有依据的总体判断与局限。 |
| 代码宿主 | 控制数据准入与运行边界，计算数字，解析引用，保存和核验有效版本。 |

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
# 在 .env 中填写 DEEPSEEK_API_KEY；双路搜索另配 TAVILY_API_KEY。
# 研究模型也可启动后选择 ChatGPT 订阅并登录。

tradingagents web --port 8765 --open
```

安装命令显式使用官方 PyPI，避免镜像访问异常。默认 A 股安装不包含与 Web 依赖冲突的 mootdx；既有环境修复与通达信补充能力见 [A 股数据能力](docs/operations/a-share-data-capabilities.md)。

订阅登录后，模型列表随账户官方目录更新；权限和额度由官方服务确认。详见 [ChatGPT 订阅配置](docs/operations/chatgpt-subscription.md)。
新建 ChatGPT 研究支持显式推理投入配置，并保持历史恢复的原请求语义；登录刷新具备按账户的暂时故障退避。

Web 仅绑定 `127.0.0.1`，自带前端，运行时无需 Node.js；运行记录保存在 `~/.tradingagents/`。凭据仅放在被 Git 忽略的本地配置中。数据权限与配置见 [.env.example](.env.example) 和 [Web 操作说明](docs/operations/evidence-research.md)。

## 当前限制

- **覆盖有限**：公开来源可能缺失、限流或无法验证历史时点；部分历史估值能力依赖 Tushare 凭据和权限。交易日历优先使用深交所官方月历，结合指数日期与通达信见证，Tushare 仅作最后备源。
- **研究质量仍需验证**：运行完成可能仍是 `partial / LOW_CONFIDENCE`；证据核查通过不代表经济原因或合理价值已确定，也未证明预测准确率提升。
- **产品范围明确**：当前维护本地 A 股 Web 研究；CLI 分析不再维护，旧流程保留历史读取与兼容恢复。

## 深入了解

| 想了解什么 | 文档入口 |
| --- | --- |
| 当前目标、研究流程、模块职责与扩展入口 | [系统架构](ARCHITECTURE.md) |
| 创建、阅读、模型配置与恢复 | [Web 操作](docs/operations/evidence-research.md) |
| 开发环境、修改路由与验证 | [开发指南](CONTRIBUTING.md)；编码 Agent 另读 [AGENTS.md](AGENTS.md) |
| 按需技术参考与历史追溯 | [文档索引](docs/README.md) |

编码 Agent 从 [AGENTS.md](AGENTS.md) 开始；当前行为以代码、契约和当前状态文档为准，历史计划不是实现证据。


## 致谢与许可

感谢 [TauricResearch](https://github.com/TauricResearch/TradingAgents) 的多 Agent 框架、[Simon Lin](https://github.com/simonlin1212/a-stock-data) 的 A 股数据参考，以及数据服务与开源库维护者。本 fork 在上游基础上发展了上述证据研究与本地工作台设计。许可见 [LICENSE](LICENSE)。
