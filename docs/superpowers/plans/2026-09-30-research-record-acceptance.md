# 统一研究记录与 Reader 接入验收

Status: Historical — 2026-09-30 本地实施记录，未发布。

Do not use this document as evidence of current implementation behavior.

对应[实施计划 B 与 D 的有限接入](2026-09-30-evidence-driven-research-implementation.md)。产品范围继续覆盖公司研究、催化研究和持仓复盘；research-only。当前行为见[机器契约说明](../../contracts/research-record.md)，本记录不代表完整流程迁移或判断准确率验收。

## 已实施

- 版本化 `research-record-v1`：来源内容、事实/推断/未知、假设依赖、挑战、执行验证记录及量化指标。从公共证据内容和元信息生成不可静默修改的 V0 哈希；V1 保留 V0 并要求执行记录；假设不能依赖其输入快照以外的证据。
- 三模式兼容生产者接入真正的提交后发布链路。经典两模式从已组装案例发布；催化从授权后的案例及冻结输入发布。恢复不重复发布，同任务冲突不覆盖。兼容记录失败保留原案例并发出安全原因，不泄漏异常载荷。
- 只读 `/reader/record`：校验提交事件、产物字节、运行身份和原案例哈希。旧历史缺失不补算；损坏和原案例不匹配不展示。
- 来源内容按允许字段选择，明确区分正文摘录、摘要与公告列表/财务/行情字段。未保存正文不编造。经典财务来源须匹配已提交 bundle hash；任意字段、非有限数字、诊断和内部路径不进入内容。
- 催化合格行情中的保存指标显示在简报下方：默认至多四项，其他指标按需展开。保留历史收益分位的正负号、窗口/样本/尾样本/算法与独立不可用原因。经典两模式暂不发布这些本地行情指标。
- 引用抽屉先显示保存内容，再显示定位和来源。补上主张/挑战到其全部直接引用来源的解析；缺少直接反证来源时保留待核查说明。来源内容和响应均绑定当前 run，跨运行或迟到响应不展示。

## 工程检查

所有 shell 命令实际通过 `rtk` 执行。

```bash
python -m pytest tests/agents/test_research_record.py tests/web/test_research_record_projection.py tests/web/test_catalyst_production_wiring.py tests/web/test_catalyst_projection.py tests/web/test_analysis_runner.py tests/test_reader_companion.py -q --color=no
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
ruff check tradingagents cli scripts/check_agent_docs.py tests/agents/test_research_record.py tests/web/test_research_record_projection.py
python scripts/check_agent_docs.py
git diff --check
```

覆盖快照内容篡改、引用越界/重复、未知/推断语义、未来证据、不可用数值、保存指标输入哈希、公共字段选择、真实 RunStore 发布/读取、经典提交边界、催化运行/恢复和原有 Reader。前端覆盖迟到/跨运行响应、正收益分位、原文缺失与文本转义、全部引用来源、抽屉焦点/Esc/背景恢复。静态资源已重建并保留在改动中。

Python 112 项通过；前端 43 文件 / 309 测试通过。类型检查、构建、Ruff、文档检查（59 页）和 whitespace 检查通过。没有运行或宣称整个仓库 pytest 通过；没有调用真实模型或付费研究。安装仍报告既有依赖审计告警，构建有主 chunk 超过 500 kB 的提示，本批未扩大到依赖升级或拆包。

## 浏览器边界

使用临时独立 RunStore、合成供应商输入及实际 FastAPI、提交产物、HTTP 与重建 SPA，在 `127.0.0.1:8889` 检查。页面判断明确标为模拟验收材料。这是正式组件与读取链路的验证，不是静态样稿，不是实际公司的研究结果，也不是来源对主张支持关系的人工验收。

检查 1440×900 桌面与 390×844 手机 CSS viewport。页面宽度分别为 1440/390，无横向溢出；手机四张默认指标卡左边界 16、右边界 374。确认四项默认摘要、更多指标展开、来源字段先于定位与来源元信息，以及引用抽屉内容。该检查不代表原生浏览器 200% 缩放、所有模式完整视觉或整套 Playwright e2e 验收。

## 未完成与下一步

- 当前两种原流程的转换记录没有独立工具验证，模型 disposition 不升级成执行结果。
- 尚未实施三模式共用研究图、模式专项政策、分维度判断、验证执行器、Markdown/JSON/Reader 完整同源输出及完整已认可阅读层次。
- 默认继续 classic；未改变原有请求/预算/数据资格门槛。B 契约仍需 C 批原生生产者接入后做实际工作流验收。
- 真实 LLM 对照、准确性和阅读效率人工评估、上游剩余选择性适配属于后续 C/D/E 批。
- 没有提交、推送或修改/删除默认用户数据。
