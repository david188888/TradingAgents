# 原生研究数值声明与冻结证据对齐

- **Status: Frozen Design**
- 日期：2026-10-14。
- **Do not use this document as evidence of current implementation behavior.**
- 用户已于2026-10-14确认整链范围、批准本设计并授权本地实施；未授权Git发布或真实模型试验。现役实现见[数值合同](../../contracts/numeric-narrative.md)，本稿保留批准时的设计边界。
- 来源：[工程诊断核查](../../reviews/2026-10-14-external-engineering-diagnosis-verification.md)。现役合同见[统一公司研究](../../contracts/unified-company-research.md)。

## 目标与成功边界

修复“证据是18.4%，模型写25%，合法引用仍能通过”的输出门禁缺口。新建研究的可核查数量由冻结资料或已保存的代码计算结果提供，模型负责解释及选择引用。数值、单位、期次、预测/实际属性必须一同绑定，不能只核对裸数字。

用户已确认覆盖新建研究的整条输出链：V7三专项、挑战、定向回应、综合及可选关注点回应，并包含它们复制到Reader、Agent产物页、Markdown及降级汇总的文本。限定现有资料和算子，不新增数据源、研究轮次、模型评判器或调用预算。角色独立时限、行业扩展、新闻去重、人工暂停均不在本方案内。

成功意味着本方案覆盖的显式数量只能通过宿主片段发布，该片段的值、单位、期次和basis由冻结输入决定且不能被模型删改。自由文字仍可能把正确片段描述成相反含义，例如“公司已实现{{num:机构预测EPS}}”；数值门禁本身不能确定性识别所有此类矛盾，不能承诺整句没有属性/指标混淆、自然语言关系或经济解释已验证。原始资料、来源标题和用户问题继续标为来源/输入，不因包含数字变成已核验公司事实。本方案选择保留开放定性解释；完整句式约束或语义判定是另一个需要用户选择的设计范围。

## 三种办法与选择

| 办法 | 收益 | 代价与问题 |
| --- | --- | --- |
| 保留自由文本，抽取数字并与来源比对 | 模型输出改动小 | 难判断一个数字对应的指标/期次；模型申报侧表可漏报，全文误差阈值容易误放或误拒。 |
| **模型引用冻结目录项，代码生成完整数值片段（推荐）** | 值/格式由宿主拥有；限制权限可重复校验，无额外模型调用 | 需要目录、受限文本协议、模板到正式提议的绑定，以及所有输出消费者一致处理。 |
| 另加模型做事实核查 | 能理解较多表述 | 新调用、成本与不确定性；不能成为确定性发布门禁，需另有质量评价。 |

选择第二种。模型不得在事实数量槽位填写值，也不接受把错误25%静默替换成18.4%。它必须返回合法目录引用或重新给出定性描述；错误进入现有有限修复/降级路径。

## 冻结数值目录

新增代码拥有的纯函数边界，拟放在 `research/numeric_catalog.py`、`research/numeric_narrative.py`，契约放在 `agents/schemas/_numeric_narrative.py`。职责分别为：从已验证记录建目录；按角色/每个输出项投影权限并编译文本；声明目录与校验凭证。没有网络、动态公式、任意JSONPath或Markdown驱动的权限开关。

目录项包含：`anchor_id`、有限字段/算子定义、证券及分部/同业/机构身份、`basis`、精确值字符串、单位、报告期/频率或报价时间/历史窗口、必要事实ID、输入证据ID、源字段选择器及内容hash，或计算版本与输入hash、局部限制。`anchor_id`由版本、快照、来源/计算输入及选择器产生，不依赖模型文案、顺序或显示舍入。

`basis`区分实际披露、行情观察、机构预测、代码计算、会计核查、假设参考区间。原数据冲突保留独立来源项及冲突状态；不平均、不悄悄取最新。`None`、不可用、未准入、截断、歧义口径不生成数值项。空白不等于零。

| 首版目录来源 | 必须保留的语义 |
| --- | --- |
| 三表六类核心财务原值 | 复用 `verification_tools._financial_operand` 的精确值及资格规则；合并口径、CNY、期末日期和已知频率。没有证据的单季/累计频率不得推断。 |
| 官方数值行及明确经营分部行 | 当前/上期、H1/FY/Q2、分类名称、原单位、归一单位、页码；排除含义歧义的毛利率变化glyph。 |
| 行情估值快照、最后价格bar | 币种、元/股、倍数、市值单位、时间、结算/未结算、复权与锚点。未结算快照不得称收盘价。 |
| 已保存available风险指标 | 值、原单位、真实窗口、样本、计算版本、输入hash；比例变百分比是显示转换，不改变值或负号。 |
| 机构EPS预测 | 机构、预测年、报告ID、发布日期；宿主片段明确写“机构预测，非已实现”。预测年可以晚于分析日，发布日期不能越过cutoff。 |
| 已有局部核查及估值结果 | 按闭合计算分支读取结构化输入，不从label/method抽数字。冲突检查不能称已核验一致；参考区间标注假设，非内在价值。完整估值历史绑定 `valuation.inputs`，不能用只保留末三行的证据摘要重算分位。 |

派生值仅允许现有闭合算子。首版为已准入的明确同口径年度/半年官方current/prior行提供财务差额与同比：同指标、同期长度、同来源家族，base>0，复用现有Decimal规则；负/零基期、Q2与H1混搭不生成增长项。三表仅有end_date而无明确期间口径时提供原值，不主动生成同比。其余值只引用已保存metric/check/valuation，模型不能提公式、增加ROIC或猜EPS。

“已保存”不豁免新目录资格。财务difference/growth核查结果仍检查字段、来源家族及明确期间长度/频率；vendor三表只有end_date时，不把该派生结果建为差额/同比anchor。新策略下同类condition.check也必须有此资格，否则走有限修复（可改为check:null及定性条件），不得先执行旧宽松growth再借结果建anchor。原值value不需要猜期间长度。历史身份的核查规则不改；历史宽松结果可保留审计，但不能移入新策略目录。

财务金额以权威精确字符串为准；已有float统计按其保存值的规范字符串读取，不声称Decimal恢复了原始精度。显示预设由代码选择并随策略冻结：金额可原CNY/万元/亿元，share price与EPS为元/股，倍数为倍，return fraction可转百分比；百分比与百分点不互换。金额亿元两位小数、价格/EPS四位、比例百分比两位、倍数两位，统一Decimal `ROUND_HALF_EVEN`。校验比较“按预设渲染的精确结果”，不使用通用相对误差。

目录硬上限每份512项，按稳定身份排序，不静默截断；超限返回 `numeric_catalog_limit`，保留基础事实与明确目录不可用限制，模型仅可定性表述。每文本最多8个片段、每阶段最多64个片段；超过则进入该阶段有限结构修复。目录构建失败不能使已经保存的基础公司资料消失。

## 输出协议与编译顺序

新策略模型使用 `NumericStageEnvelopeV1`：`proposal` 保持对应阶段的现有字段结构，但受控文本字段为模板；附有有限的观察计划参数。宿主提供提示内别名及允许片段，模型在文本引用 `{{num:n_alias}}`、`{{meta:m_alias}}` 或局部 `{{plan:p_alias}}`，不填写观察值、unit换算或舍入位数。别名只在独立token解析器处理，不把现有 `translate_references` 改成全文替换。

envelope还包含 `structured_bindings`：每个模型填写的check operand/谓词及challenge observation_date都由宿主允许的字段路径绑定到数值目录或本项plan；多余、遗漏、重复路径拒绝。结构化字段可携带数字/日期字面量，但必须满足下方专用规则，不能借此获得自由文本literal例外。

`num`展开为含指标、期次/窗口、数值及单位的完整短片段；预测与假设参考标签不能由模型去掉。`meta`只能引用宿主提供的证券/公司名、报告期、已保存来源标题或已保存条件等背景信息，明确标为身份、期次、来源标题或原条件，不作为数字事实；不得以复制来源标题代替数值引用。已有事实或子输出全文复制走宿主继承路径，不由模型创建任意文本escape。

例如目录中“2026H1营收同比增速18.40%（同口径官方披露的代码计算）”可嵌入“{{num:n_growth}}，但低基数可能影响持续性”。返回裸“营收增长25%”、不存在的token、错角色token、重复嵌套token或模型自填单位均拒绝。目录没有合格增长项时改用定性描述或承认缺口，不要求模型填数字。

观察阈值不是公司事实。`plan`仅能出现在必要/失效条件、proposed_test、next_check、suggested_next_check中；有限结构包含数量阈值/单位/comparator或未来观察日期。宿主必须渲染“模型提出的观察阈值/日期，非已披露事实”。数量单位仅CNY、CNY/share、ratio、percent、multiple、count；若对应已有 `check.predicate`，值/operator/unit必须完全一致；日期只能晚于分析日且不能伪装为披露时点。理由、实际增长陈述和估值锚点不能通过plan绕过事实资格；后续引用已保存条件须精确继承原条件及标签。

模板先完成JSON/schema验证、ID反别名、每项引用权限与数量覆盖检查，再编译为现有canonical阶段提议字符串。编译后重新执行现有引用/条件/维度/回应及公开记录门禁，并检查原长度限制；溢出拒绝，不截断合法数值片段。随后才保存accepted提议并生成假设、条件、挑战、回应ID。没有已接受字符串的事后改写。

数量覆盖门禁针对每个模型文本字段的所有literal段，不只检查模型主动申报片段：

- Unicode兼容数字、阿拉伯整数/小数、科学计数、区间/分数/正负号、百分比/百分点/货币/倍数/物理单位数量均需token；验证视图可做NFKC，但不改canonical文本。
- 日期、年度、证券代码、包含数字的公司/产品名也必须使用meta token，不由通用“日期/六位代码白名单”放过。零宽字符或拆开数字不能规避阿拉伯数字检查。
- 汉字显式财务数量包括百分之/千分之/万分之、成数、汉字数字加钱币/百分比/股/吨/辆/倍等单位及明确数量分数；英文数量词加percent/per cent/basis points/currency/multiple亦在支持语法中。裸定性词、一般“一致/进一步”不误作数字。
- 不能可靠落入该有限语法的隐喻、关系描述和隐含算术不获“已事实核查”标记。此门禁不声称完备自然语言语义理解；测试与文档须明示该限制。

实现计划必须将上述语法及反规避样例做成code-owned确定性词法表，不新增LLM判断；支持语法版本进入策略。字段完全不含数量时也需“已扫描”凭证，不能靠缺少侧表绕过。

## 字段与权限矩阵

| 阶段 | 受控模型字段 | 数值权限 |
| --- | --- | --- |
| 三专项 | statement、condition.text、alternative_explanation、unknowns | 每假设的num必须被其supporting_fact_ids覆盖；公共foundation不扩权。unknowns无事实支持关系，只允许定性，不使用num/plan；其中必要身份/期次可以用meta。 |
| 挑战 | statement、proposed_test | 仅目标假设的合法事实、原条件及其已经绑定的核查；本条挑战不能借用别的假设数值。 |
| 定向回应 | rationale、remaining_unknowns | 按每个challenge验证原有 `allowed_facts_by_challenge` 和本条保存核查，不能用stage内多挑战权限并集。remaining_unknowns只定性。 |
| 综合 | judgement、next_check、dimension.judgement/limitations、模型challenge rationale、支持/反对理由、adjudication.rationale、change_condition.text | 维度使用自己的合法claims；理由引用response时使用现有回应fact规则；裁决仅本challenge/reply范围。overall judgement仅已选key_claim_ids及其依赖。limitations定性；change_condition由父假设精确继承。 |
| 可选关注点 | answer、limitations、suggested_next_check | 仅其显式claim/evidence引用所覆盖且baseline合格的目录项；来源标题/用户focus数字不可升级为公司事实。limitations定性。 |

模板中的num依赖必须进入现有引用字段，不自动补引用，不放宽旧门禁。同一来源下不同字段不能因为evidence_id相同就视为同一事实；目录项同时绑定必要fact与字段选择器。数值正确不自动证明“增长改善/低估/风险消失”等语言关系。

结构化字段与自由文字执行同一项语义绑定：

| 结构化字段 | 规则 |
| --- | --- |
| `check.current/base` 的证据、table/field/report_period | 必须对应本假设supporting facts所覆盖且已准入的精确字段/报告期；不能从literal日期造一个不存在的operand。difference/growth额外执行上文频率资格，value保留现有原值资格。 |
| `check.predicate.threshold/unit/operator` | 必须绑定同condition的plan数量参数并完全相等；原本就可由模型提出，属于阈值而非事实。单位与operation/metric本来要求的单位一致；ratio阈值0.25渲染25%是确定显示转换。无check的文本计划也必须有自身显式参数及非事实标签。 |
| `challenge.observation_date` | 缺省可以继续None。已知历史观察日须绑定该challenge所选核查/风险的合格观察anchor且日期一致；不能凭空补过去日期。未来日必须绑定本challenge的plan日期，严格晚于analysis_date，保持future_observation/未执行语义；不能使observed_risk成为已观察风险。 |
| `challenge.check_id/observed_risk` | 保留已有闭合枚举/核查绑定；对应num与observation_date必须属于该核查及target hypothesis。不因为有合法日期或plan就确认风险。 |
| 其余机器数值/日期字段 | 宿主ID/index/count及既有字段固定值沿其canonical schema，不开放模型写入新原值。任何新增可写数值字段必须先加入此allowlist及凭证，不能默认忽略。 |

future observation_date与已知历史观察使用不同binding kind，不能同时出现；晚于cutoff的日期只作为计划，来源发布日期仍受原PIT资格约束。已有地方字段恢复/复制时继承相同structured binding，不允许文本阈值和机器谓词形成两个数字。

宿主生成的静态原因文本无需模型扫描；但复制模型字段的retained_summary、默认失效条件、被gating覆盖的文字必须通过同一编译/继承器映射凭证。`retained_summary`不能继续在数值或单位中间 `[:400]` 截断：按完整片段/完整原句在限长内组装，过长时显示定性保存摘要并引用原产物，完整字段仍可追溯。

## 凭证、持久化与兼容

新建V7身份冻结 `numeric_narrative_policy=anchored-narrative-v1`，其语法、目录、渲染预设和算子版本是冻结策略的一部分。历史V1–V7身份缺少标记时继续原schema/prompt/cache/序列化/Reader/Markdown逻辑，不注入默认策略或空列表。未知策略拒绝恢复，不能降回旧校验。

受验证stage凭证保存context与prompt hash、模板及局部参数、canonical提议hash、目录hash、所有受控字段路径及text hash、每个引用的锚点与渲染片段。路径使用宿主allowlist与原始hypothesis/reply下标，不引用尚未生成的实体ID；生成正式ID后由共享映射器生成公开owner路径。模板编译和ID生成规则必须由adapter/kernel/Reader共享，不复制算法。

公开manifest采用可独立重建的有序片段，而不是裸anchor集合：每个受控字段均有按顺序排列的literal、num、meta或plan segment及局部参数，空数量字段也有literal和扫描版本；同附structured bindings。读取时按保存策略重新扫描literal、验证权限/来源/结构字段、渲染各segment，再按UTF-8连接并核对实际字段字符串与text hash。不依赖前端UTF-16区间，也不从已渲染正文猜原范围；模板token只做一次非递归编译，来源内容中的token样式不可二次执行。宿主复制/摘要的manifest记录父owner/字段及完整片段选取，重建其实际最终文本，父引用必须先于子输出且不得形成环。

公开记录增加可选 `numeric_attribution`，包含策略、所用锚点及重建所需公开输入绑定、最终字段manifest。种子包含合法catalog及自身事实绑定；最终记录包含所有实际字段manifest与明确的catalog缺口。该字段缺失时从序列化省略；有新身份时必须存在并有效，字段和策略不能单方省略。目录不引用其自身所在record的最终hash，避免循环：仅绑定既有快照、源content或保存计算输入；manifest绑定实际文本hash与已生成owner ID。

公有manifest不含完整prompt、无效响应、私有推理或原始provider envelope。有效模板是受验证输出结构，不是prompt。跨来源冲突及预测属性显示为来源语义，不提供总括“全文通过事实核验”徽章。

原生adapter新调用、adapter cache/repair/candidate、kernel `_call` cache/recover/custom caller、专项merge、回应merge、最终组装和发布前均检查同一策略和凭证。custom caller在新策略下同样提供envelope，不能交旧纯字符串绕过。存储缺凭证、错hash或不同快照是checkpoint/persistence冲突，不能因为缺验证就再次调用模型补表。

Reader record/process/选中Agent、Markdown、原生publication均按保存身份验证；AgentDTO仅返回已接受canonical提议及安全绑定子集，不展示未验证template或候选。前端消费已经编译好的文本，不重新换算/改值；证据面板可展示数值的单位、期次和basis。TypeScript facade、fixture和生成SPA资产需在实现时同步。

关注点有独立数值凭证，保存于focus artifact并绑定已冻结baseline hash；baseline的numeric_attribution必须在 `native.output`之前完成。focus不能回写baseline，恢复/发布/Reader重新校验它自己的context、输出与数值绑定，失败仍仅使补充回应不可用。

## 失败、修复与交付

闭合数值错误至少区分 `numeric_literal_unbound`、`numeric_anchor_unknown`、`numeric_anchor_scope`、`numeric_basis_mismatch`、`numeric_plan_mismatch`、`numeric_render_limit`、`numeric_manifest_binding`、`numeric_catalog_limit`。仅保存固定类别、允许字段路径、原始索引与计数；不把无效全文、任意validator消息或模型数字带进诊断。

| 失败位置 | 行为 |
| --- | --- |
| 结构有效的单假设数值错误 | 沿现有一次有限结构修复。修复有效替换原提议，不合并main/repair；修复失败/预算拒绝时只保留原提议中独立合法的hypothesis及原索引，过滤对应凭证。共享unknowns不合法则阶段整体拒绝；恶意/损坏schema主响应不能部分接受。 |
| 挑战或回应数值错误 | 使用该阶段现有修复机会；仍失败则既有unavailable/partial处理，不把失败当作合法“零挑战”，不新增per-item salvage语义。 |
| 综合数值错误 | 一次现有修复仍失败时交付已有基础/有效专项汇总，综合未完成、stance为空，保留来源与失败原因；不自动改错数字来保住总体评级。 |
| 可选focus数值错误 | 不增加修复、重试或预算，保存invalid_response不可用，主报告保留。 |
| 缺数字所需资料 | 不编数；合法定性输出可以继续。完整源/公司基础资料不因某项数字未进入目录而消失。 |
| 已保存凭证缺失/不一致、取消、整轮截止、checkpoint冲突 | 沿原fail-closed生命周期，不通过部分隔离吞掉，不重放未知dispatch，不读时补表。 |

数值校验占用现有repair预算，不额外增加模型阶段或12次总请求上限。读取零模型/数据请求。研究可读、完成、覆盖与质量仍分开；数值片段对齐不提高经济判断置信度或改变现有stance ceiling。

## 验收与实现边界

实现前先补纯本地回归和主链端到端合成fixture，再实现目录→模板编译→cache/kernel→发布/Reader/Markdown/focus。无需真实模型调用验收确定性门禁；真实供应商对新输出协议的可靠性另行授权测试，不能从mock通过推导。

必须覆盖：18.4→25裸数拒绝；合法anchor得到固定18.40%；财务元/亿元舍入；ratio/percent/百分点；当前/上期及H1/Q2/FY错配；负/零基期；已有check不能旁路频率资格；多来源数值冲突；forecast/未结算片段的标签不可删改；历史窗口/样本/复权；None及不可用不能变零；未知/越权token；漏报文本与结构字段；全角/零宽/科学计数/汉字及英文财务数量；meta标题不能成为数值anchor；计划阈值与check精确绑定；历史observation_date必须有真实anchor、未来日期明确是计划；unknowns的num/plan拒绝；编译膨胀超长；有序片段及父子manifest重建/反循环；汇总截断不切数值；main/repair互斥及原索引隔离；所有cache/custom caller路径；policy/manifest错配及未知dispatch；全部角色输出和focus独立失败。另以“已实现{{num:预测}}”等案例明确证明外围语义仍是未覆盖限制，不把片段标签正确宣传为整句事实核验通过。

兼容验收以历史V1–V7合成记录与checkpoint为基线：无策略时schema、prompt hash、canonical bytes、实体ID、Reader DTO与Markdown一致；不能用“可读取”替代字节/绑定比较。新增策略在Reader回放与导出前验证，不触发修复调用。使用现有Conda环境及tracked tests；实现frontend后执行typecheck/build、相应Vitest/Playwright并纳入生成资产。

## 设计批准时的记录

独立spec审查：第一轮发现结构化日期/谓词遗漏、保存check的频率旁路、外围语义保证过宽及unknowns权限冲突；已修订，第二轮结论Approved。审查之后用户批准设计及本地实施；真实模型测试仍需另行授权。

本设计阶段只新增设计稿及索引，未修改行为代码。后续实施与验证记录见[本地实施记录](../plans/2026-10-14-numeric-narrative-implementation.md)。既有ChatGPT/sidebar及先前调查改动继续保留；记忆只读，Hindsight未使用，不做分支/worktree清场。

批准范围包括具体模板引用协议、数量/日期资格、局部失败处理及“数值片段有保证、外围解释仍需复核”的明确边界。批准不扩大到角色独立时限、兼容新闻去重或行业数据扩展。
