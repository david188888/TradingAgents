# C2：原生三模式研究与生产接线

Status: Historical

Do not use this document as evidence of current implementation behavior.

承接已认可的[统一方案](2026-09-30-evidence-driven-research-and-reader-proposal.md)和[C1](../plans/2026-10-02-bounded-verification-acceptance.md)。research-only、已有总预算和旧 run 只读／恢复语义为不变量。用户已授权继续 C2；用户随后确认推荐的独立 evidence_v1 接线方案，旧 profiles 保留。实施与验收查[公开接线验收](../plans/2026-10-03-native-research-public-wiring-acceptance.md)。

## 共享内核

`research/native_record.py` 从已冻结、资格合格的 source context 建立 native V0。财务字段按代码 allowlist 提取，保留精确报告期和披露日期及金额 CNY；公告列表事实只陈述披露标题，不宣称事件实施或正文已核实；行情事实只来自已有合格计算。身份必需，不满足则不调用专项。首次调用前保存源快照／模式／问题／原持仓假设的身份摘要。

三个职责为 operating_quality、event_context、market_context。按固定顺序预留 MAIN_ANALYSIS，最多并发两个，按固定顺序汇合；职责只接收自己的事实与源字段，不读取他人的草稿。无合格材料则跳过。事实由代码生成，模型输出有限 inference／假设、所依赖的事实和失效条件／必要条件及可选 C1 结构化检查，不生成新 fact。JSON/schema/引用错误经过现有单次结构修复后仍不合格则记录失败／未知，不强化材料。

挑战调用一次，允许零挑战。仅看到匿名假设、依赖事实、来源和可核查条件，不看到专项作者、最终判断或优先级。至多三个单目标挑战，风险类型沿用 canonical 清单。模型选用已保存的 condition ID，不能临时修改数值条件；代码生成绑定 challenge/hypothesis/V0 的 C1 plan。无可执行条件的挑战仍完整保留，不能为制造验证而编造规则。

调用 C1 后最终综合一次，输入全部保存的事实／假设／挑战／V0/V1／执行 outcome。必要条件满足不是整条假设被验证；关键挑战均保持 unresolved 或由有依据的模型解释保留其限制，本批不授予 predicate_only 结果关闭整条挑战的能力。未知／预算拒绝／工具失败与未触发失效条件不能升级结论。

## 输出契约与门槛

`_research_assessment.py` 定义附加在 `ResearchRecordV1` 的可选原生综合字段；旧记录缺省为空。包括简短 judgement、code-owned 模式维度的判断／状态／claim 与 challenge 引用、最多三条主要依据、最大疑点和下一核查。每个模式的维度必须齐全，不允许压缩时丢弃 valuation 或 holding_thesis 的未知。company 包括经营、估值和市场背景；catalyst 包括经营、催化兑现和市场背景；holding 包括原假设、经营、估值和市场背景。

身份、快照、日期、重复／悬空引用错误拒绝产物；各维度分别按必要来源与未解决关键挑战退化。未知事实不能作为结论依据；inference 依赖的论断最高为 conditional，不能标成已证明。C1 的局部反证不能证明整个经营结论反面也成立。当前缺合格估值数据则 valuation 保持 unresolved；缺用户原假设则 holding_thesis 保持 unresolved。持仓事实必须与 ticker／截止一致，不猜账户或原论点。84 天只属于 catalyst；公司／持仓不套用该展望。

事实、摘要、阅读 JSON 与 Markdown 从同一已提交 native record 生成；不使用第二摘要模型。Reader 在 native 路径直接显示已有原生判断和条件核查，保留量化／来源展开。该接入不宣布完整 D 布局／浏览器阅读验收完成。

## 持久化与执行边界

共享 workflow 使用 caller 的原有 durable journal／ledger，不创建第二本预算。新增 native workflow identity，包括版本、模式、问题、数据政策、配置、原持仓假设。旧 profile 的指纹不改；新 profile 与旧 checkpoint 不兼容时明确拒绝，不重算或删除用户数据。现有源 collector／可观测 HTTP transport 重用，不扩大 vendor 准入或 source qualification；内部数据窗口复用不能把 84 天宣称为公司／持仓的研究展望。

模型每次 reserve→持久化 dispatch→调用→保存经校验 JSON→settle；复用既有 repair/retry 分类和总额度。checkpoint 缓存所有角色、计划、C1 结果和最终候选；角色结果与输入身份/摘要绑定，已改变内容拒绝。恢复继承未知调用预算，缓存重读无模型／供应商；取消阻止新的执行和发布，已经完成的验证仍保留。超时与取消使用既有生命周期仲裁。

Native publication 为 mandatory gate：验证候选与已提交相同 task 是否一致，经 manager lifecycle authorization 后提交 record，失败使运行失败，不能走兼容 additive fallback。提交至多一次，读取已提交快照不 dispatch。ReportArtifactWriter 对 native 输出生成同源 Markdown，恢复复用内容且拒绝冲突。run.completed、read-ready、质量与数据完整性保持独立。

## 公开接线选择

已确认独立 `evidence_v1` 试用入口，公开 mode 接受 company_research／catalyst_research／holding_review，默认仍 classic，旧 catalyst_v1 保留原执行和恢复。使用服务端 feature flag 控制新建；试用新 profile 不新增界面选择项，先支持显式程序接口／Web API。对应 request／snapshot／manager factory／resume／retry／event roles／TypeScript／读写契约须一致，不能静默退回 classic。普通 CLI 原路径保留；不得声称已有新的 CLI 参数。扩展 catalyst_v1 的替代方案未采用。

## 验证与交付

先验证共享核心的三个模式与 source／条件／引用污染，再验证真实 RunStore、RunManager、生产 caller（离线 client）与 HTTP request→runner→提交→只读→Markdown→重读／恢复。覆盖五次主模型上限、模型 repair/retry、稳定串并行、零挑战、缺估值／原假设／价格、关键挑战不因条件支持而关闭、取消发生在 C1 结果保存后／最终发布前、坏候选／publication 失败／同 ID 冲突、改配置／角色输出缓存污染、断点恢复不重取或重算。

旧 classic/catalyst、C1 及记录投影回归；Ruff、docs、前端 ci/typecheck/test/build 与 tracked static 同步。全量比较沿用 e0bb17b 的同环境 12 项既有失败，明确排除 live DeepSeek 并关闭 dotenv。独立 spec／实现审阅，不执行真实模型或供应商请求，不宣称准确率提高，不 push／PR／默认迁移。本批之后完整 D 和 E 的质量／成本对照仍待实施。
