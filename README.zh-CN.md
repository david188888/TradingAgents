[English](README.md) | 简体中文

# TradingAgents

TradingAgents 是一个基于 LangGraph 的本地多智能体研究框架，源自 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)。本 fork 主要面向中国 A 股：收集合格证据，通过经营、事件、市场专项与独立挑战检验研究假设，并生成可复核的研究记录。Web 工作台是持续维护的产品入口，支持公司研究、催化研究与持仓复盘；CLI 分析保留为不再维护的旧代码。系统不生成订单或目标仓位，也不构成投资建议。

3.0.0 统一 Web 新建流程并退休旧研究模式的新建入口。升级边界与主要变化见
[大版本发布说明](docs/reviews/2026-10-05-v3-release-notes.md)。

## Demo

观看一个已完成的历史 A 股研究样例演示，时长 20 秒。视频展示上一版界面，保留中文并配有英文说明，仅用于展示研究流程，不构成投资建议。

[![TradingAgents demo：002335.SZ 研究样例](https://david188888.github.io/images/tradingagents-demo-poster.jpg)](https://david188888.github.io/videos/tradingagents-demo.mp4)

[打开 20 秒演示视频](https://david188888.github.io/videos/tradingagents-demo.mp4) · [查看项目页面](https://david188888.github.io/en/projects/tradingagents/)

## 研究流程

Web 是持续维护的产品入口，单公司和批量新建统一使用 `evidence_v1`：
合格证据冻结 → 经营／事件／市场专项假设 → 独立挑战 → 有界条件核查 → 分维度综合 → 保存记录与报告。
CLI 分析代码保留为旧入口，此后不再维护；启动网页的 `tradingagents web` 命令继续使用。

公司研究覆盖经营质量、估值和市场背景；催化研究展望未来 84 个日历日；
持仓复盘使用用户提供的真实或模拟持仓和原假设。批量采用相同的公司研究流程。
角色、数据窗口与调用预算由代码固定，不再使用旧的多空辩论深度或分析师选择。

桌面结果页先呈现研究范围与独立综合判断，再展示关键依据、最大的疑点与下一步、已执行检查、估值定位和量化背景。
点击“核对依据”可在侧栏查看绑定事实、保存原文或明确标注的来源字段、时点和概念解释；窄桌面使用抽屉。
“研究过程”说明各环节的职责、状态与产物；“Agent 产物”可回顾保存的专项、挑战和综合提议，追踪其在最终记录中的处理。
“完整记录”保留全部内容，“技术诊断与执行记录”用于查看实际角色、调用记录口径与故障。
这些入口只读已保存内容，不重新取数或调用模型；缺失调用记录显示“未记录”或已知下界，不填零。
可选的“补充关注点”在基础研究持久化后单独回应，只使用保存证据，展示在基础报告末尾。
它不参与取数、专项、挑战或基础综合，也不能修改基础结论、质量和下一步；未填写时没有补充调用。
补充最多 1 次模型调用，计入原 12 次总额度，无修复或重试；普通补充失败不影响基础报告。
历史 V1–V5 保留当时的研究问题语义，不会重写旧报告。
运行完成仍可能是 `partial / LOW_CONFIDENCE`，不能视为证据充分。

新版优先使用有界公开公司资料、新浪财务表、巨潮披露与合格腾讯／新浪复权行情，
并保留 Tushare 备用来源。V4 增加带报价日期的腾讯估值快照和 Tushare PE/PB 历史。
估值由代码计算；只有合格年度合并归母净利润和足够历史倍数同时存在时才生成参考区间。
缺失输入保持不可用。当前抓取的历史倍数不证明历史档案时点可用性；区间依赖盈利和倍数假设。

新运行使用 V6，沿用 V5 的数据与核查规则：选取正式报告、摘要及运营公告，保存页码、文档校验、明确的当期／同期数字与
现金流桥，由代码核对三项有限的证据问题。有日期的机构 EPS 和同交易日行业候选报价补充估值背景；
可选来源失败保留其它局部核查结果。结果页分别显示证据问题已回答、数据支持的风险和未来观察。
现金流变化的经济原因、持续性及合理价值仍需判断；核查通过不会自动关闭这些问题或提升研究评级。

旧 `classic` / `catalyst_v1` 记录仍可阅读；合格中断任务按原版本与已消耗预算恢复。
旧流程新建和新运行重试返回 `410 research_profile_retired`。
新版默认启用，`TRADINGAGENTS_EVIDENCE_ENABLED=false` 可停用新建、批量及重试，历史读取和恢复仍可使用。
现有记录不自动改写或删除。

详见 [Web 操作说明](docs/operations/evidence-research.md)、
[统一研究记录](docs/contracts/research-record.md)、[估值规则](docs/contracts/valuation-assessment.md)
及[系统架构](ARCHITECTURE.md)。单标的真实运行用于验证可用性，不证明预测准确率或已完成同证据质量对照。

## 快速开始

需要 Python 3.10 或更新版本。为所选 LLM 供应商配置 API Key，并按需配置数据或新闻服务；默认 LLM 供应商为 DeepSeek。请将凭据保存在被 Git 忽略的本地文件中。

```bash
git clone https://github.com/david188888/TradingAgents.git
cd TradingAgents
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[china,web]"

cp .env.example .env
cp tradingagents.config.example.json tradingagents.local.json
# 在 .env 中设置 LLM Key（例如 DEEPSEEK_API_KEY），并配置所用数据供应商
# （例如 A 股财务数据可设置 TUSHARE_TOKEN）。
# 如需修改默认路由，可编辑 tradingagents.local.json。

tradingagents web --port 8765 --open  # 本地 Web 工作台
```

Web 服务仅绑定到 `127.0.0.1`；运行时无需安装 Node.js。配置可来自 `TRADINGAGENTS_*` 环境变量、本地 JSON 文件或交互式提示。结果、缓存、记忆日志和新闻缓存路径留空时会使用内置默认值。完整选项见 [.env.example](.env.example) 和 [default_config.py](tradingagents/default_config.py)。本地运行记录和报告保存在 `~/.tradingagents/`；路径说明见[架构文档](ARCHITECTURE.md)。修改 `frontend/src/` 后，开发者应运行 `npm --prefix frontend run build`，并更新 `tradingagents/web/static/` 中的生成文件。

官方 DeepSeek V4.1 Flash 的模型 ID `deepseek-flash` 可用于快速与深度两个
模型入口；原有 `deepseek-v4-flash` 配置仍可使用。思考模式默认启用，effort
保持 `high`。显式关闭思考时不会发送 effort，以免重新启用思考。
可选 `deepseek_task_efforts` 支持按实际 Agent、阶段和辅助任务覆盖档位；
未配置的任务继承全局设置。操作与恢复边界见
[模型推理配置](docs/operations/llm-reasoning.md)。

## 更多文档

- [文档索引](docs/README.md)与[当前架构](ARCHITECTURE.md)
- [Research Reader 架构](docs/architecture/research-reader.md)与 [Web 批量分析](docs/operations/web-batch-analysis.md)
- [Agent 工作规则](AGENTS.md)、[契约索引](docs/contracts/README.md)和[贡献指南](CONTRIBUTING.md)

项目许可条款见 [LICENSE](LICENSE)。

## 与上游的区别及致谢

本 fork 保留了 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 的 LangGraph 多智能体基础。持续维护的 Web 流程增加了有界 A 股数据路由、隔离的专项假设、独立挑战、代码裁定的证据核查，以及读取保存记录的 Reader/Audit 工作台。历史 classic 记录保留此前的 Evidence Steward 与辩论路径。当前公开研究模式以研究复核结束，不再执行原有的交易决策流程。这些是本 fork 的设计选择，不代表上游没有任何类似能力。

感谢 TauricResearch 的贡献者开发 TradingAgents 框架，感谢 [Simon Lin](https://github.com/simonlin1212/a-stock-data) 提供 A 股数据参考，也感谢本项目所用数据服务和开源库的维护者。
