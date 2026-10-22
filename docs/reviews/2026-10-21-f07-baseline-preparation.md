# F07 基线准备：样本、评分口径与旧策略分数

Status: Historical

**Do not use this document as evidence of current implementation behavior.**

日期：2026-10-21。范围：用户本地已保存运行和当前工作区的离线夹具。
本记录服务于[整改待办](../plans/2026-10-21-review-remediation-backlog.md)的“基线准备”阶段。
所有分数来自 **F02 之前的策略**（无 `factual_premise_policy`），不是 `factual-premises-v1`
新契约的表现，也不证明投资判断正确。本次未调用模型、未创建运行、未写入用户数据目录。

## 1. 已确认的决定

| 项目 | 决定 |
| --- | --- |
| 样本来源 | 先用现有已保存运行和离线夹具；新契约真实运行另行授权 |
| 评分者 | Claude（`claude-opus-5-5`，开发会话内读取保存记录）打分，用户抽查 |
| rubric | [`hypothesis-quality-v1`](../contracts/evidence-benchmark.md#manual-hypothesis-rubric-hypothesis-quality-v1) |
| 重要性权重 | 按已保存严重度：critical=3、material=2、其他=1；严重错误单独计数，不并入均分 |
| 稀疏样本 | 605277.SS 新亚电子，经纯数据采集确认 |

权重继承规则：假设对应的推断 claim 被某挑战 `target_claim_ids` 指向时，取这些挑战的最高严重度；
否则为 1。总体判断（`assessment.judgement`）固定为 3，因为保存记录不给它严重度字段。
评分分歧以用户抽查结果为准，并记录原分、改分和理由。分数暂时只记录在本文，
`eval_benchmark.py` 的人工评分字段继续保持 null。

## 2. 样本清单

| 样本 | 场景 | 运行 / 夹具 | 状态 |
| --- | --- | --- | --- |
| 300750.SZ 宁德时代 | 数据充足、正常可核查 | `run_20261018T160807562817Z_6ae06213` | synthesized / neutral / LOW_CONFIDENCE，已评分 |
| 600418.SS 江淮汽车 | 已知费用前提缺口、亏损且现金流恶化 | `run_20261018T161117240227Z_021254c5` | synthesized / neutral / LOW_CONFIDENCE，已评分 |
| 605277.SS 新亚电子 | 稀疏证据 | 无运行；纯数据采集（第 4 节） | 待真实运行后评分 |
| 300750.SZ 启动失败 | 模型前失败 | `run_20261018T160405191256Z_3149e2d5` | failed，0 次模型尝试，不评分但计入分母 |
| 冲突证据 | 供应商不一致 | `tests/test_factual_premises.py::test_conflicting_suppliers_retain_attributed_sources_without_direction` | 离线夹具 |
| 江淮式前提缺口 | 缺费用观察 | `tests/test_factual_premises.py::test_jianghuai_missing_expense_is_a_question_not_a_host_observation` | 离线夹具 |
| 局部分段失败 | 综合分段降级 | `tests/test_synthesis_sections.py` | 离线夹具 |

启动失败运行的终止事件为 `missing_configuration`（`_Unavailable: invalid_fields`），
记录的是当时的分类；F06 之后的分类行为以当前代码为准。

## 3. 冻结身份

两份已评分运行与启动失败运行共享同一策略身份：`evidence-production-v7`、
`evidence-policy-v1`、`anchored-narrative-v1`、`structured-financial-checks-v1`、
`bounded-repair-then-isolate-v1`、`siwc-reasoning-v1`、
`timestamped-quote-cautious-judgement-v1`、`company-basics-local-gaps-delivery-v1`、
`native-network-retry-v1`；预算 8 主调用 / 12 总尝试；provider `chatgpt`，
专项与综合模型均为 `gpt-6-luna`；分析日期 2026-10-19。

| 运行 | 正式记录（内容哈希文件名） | V0 快照 sha256 | 固定检查输入 sha256 |
| --- | --- | --- | --- |
| 宁德 `6ae06213` | `6e74863f82ef5325c7b5ba5adb3e88c7e709827c2c35b4bc4223da85db9090a6` | `8c1a52561b412579d2fe10e220c3fbc70270449ddd82a6f9e352c79a3615990a` | `b903f1f9a85048a96110356d55c699f4178fbf7876dd65809a41e81b4a40fd66` |
| 江淮 `021254c5` | `0ab221ec7c4ed0f0481d690345aa0cfbc9556534bd5a35edbeea3b1fd56e489c` | `06d944c1b267064b25e05c177d00234fbf7174464b723bcdf741b26b15c369f9` | `e1a2931ad11228cf2e95ee1f8ae83db49df5a82e322939a8823ee9cacff400f6` |

## 4. 稀疏样本确认（605277.SS）

2026-10-21 在开发会话中直接调用 `MinimumEvidenceSources.collect()` 和 `build_native_record()`，
使用江淮运行的 effective config、内存 ledger，不经过 run store，也不调用模型。
19 次数据调用中 16 次成功；失败为两份公告 `document_security_unqualified`、THS 预测
`forecast_http_unavailable`。V0 快照 sha256
`232816cdb6245b028210dbe83667107560c0db9bfde10479f1a163b42f6b4d79`，只标识这次采集，
未保存为可复现运行；真实运行会产生自己的快照。

| 指标 | 605277 新亚电子（10-21） | 600418 江淮（10-19） | 300750 宁德（10-19） |
| --- | ---: | ---: | ---: |
| 证据条数（官方 / 供应商） | 37（25 / 12） | 69（60 / 9） | 122（87 / 35） |
| dated_forecasts | unavailable，两源均无合格行 | partial | partial |
| operating_detail | unavailable | partial | unavailable |
| 基本面 / 行情 / 同行 | qualified / qualified / qualified | qualified / unavailable / unavailable | qualified / qualified / qualified |

结论：证据量约为江淮的一半、宁德的三成，且没有预测、经营细节、行业及经营范围字段，
适合作“预测与经营细节稀疏”样本；基本面和行情仍合格，所以它不代表“财务数据缺失”场景。
采集日期不同，江淮当日的行情、估值不可用来自供应商失败，数量只能粗略对比。

## 5. 旧策略假设评分（`hypothesis-quality-v1`）

轴：S 具体性、F 可证伪、D 与决策相关、I 新增信息。权重按第 1 节规则继承。

### 江淮汽车 `021254c5`

| 假设 | 内容摘要 | 权重 | S | F | D | I | 均分 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `h.2fabdb7a` | 收入增长未转化为盈利或 CFO 改善 | 2 | 4 | 3 | 4 | 3 | 3.50 |
| `h.f70f01c7` | CFO 走弱的主要桥项是经营性应付调整转差 | 2 | 5 | 3 | 3 | 5 | 4.00 |
| `h.34f8213d` | 销售费用增加可能抵消规模收益 | 1 | 2 | 2 | 2 | 2 | 2.00 |
| `h.df46cbdc` | 回购已实施，但不证明经营拐点 | 1 | 3 | 2 | 2 | 2 | 2.25 |

等权均分 2.94；加权均分 3.21。理由：

- `h.2fabdb7a`：期间与口径来自同期字段（收入 +14.3%，CFO 由 −31.5 亿至 −52.9 亿），
  但遗漏亏损收窄（归母 −3.1%、净利润 −15.3%），I 只给 3；证伪条件是未来观察，未绑定可执行检查。
- `h.f70f01c7`：现金流桥核对差额 0.00 且固定检查通过，明确区分会计桥与经济原因并给出替代解释。
- `h.34f8213d`：引用的四个事实没有销售费用；`f.9615b28f` 实为净利润。这是已知江淮前提缺口。
- `h.df46cbdc`：主要是免责声明，证伪条件“经营持续改善”不可操作。

### 宁德时代 `6ae06213`

| 假设 | 内容摘要 | 权重 | S | F | D | I | 均分 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `h.717cea01` | 估值锚不可用，不能判断价格相对价值 | 1 | 2 | 3 | 2 | 2 | 2.25 |
| `h.3637975a` | 基金备案只代表行政进展 | 1 | 3 | 3 | 1 | 2 | 2.25 |
| `h.6078363c` | 历史波动与回撤提示市场风险 | 1 | 2 | 1 | 2 | 1 | 1.50 |
| `h.30ef1bac` | 行情事实不足以判断投资吸引力 | 1 | 1 | 1 | 2 | 1 | 1.25 |

无挑战，等权与加权均分均为 1.81。理由：四个假设都在描述证据边界或行情统计；
`h.6078363c` 的证伪条件只有“计算错误”，不是可观察的经济反证。

### 严重错误与覆盖缺口（不并入均分）

| 运行 | 类型 | 内容 |
| --- | --- | --- |
| 江淮 | 无来源前提 | `h.34f8213d` 的“销售费用增加”没有已保存事实支持；未进入总体判断与论据 |
| 宁德 | 关键遗漏 | 收入 +54.8%、归母净利润 +42.0%、CFO 仅 +2.6%，是本期最重要的经营关系，却没有任何假设或挑战；只在综合反方论据中出现 |
| 江淮 | 非严重遗漏 | 总体判断“亏损仍在”正确，但未提亏损同比收窄 |

两份运行都没有方向错误。江淮 2 个 material 挑战都绑定固定检查
（`cash_conversion`、`financial_baseline`），假设导向核查执行数为 0；宁德挑战数为 0。
江淮 `operating_quality` 分段不可用（7/8 接受），估值和市场维度因资料缺失保持 unresolved。

## 6. 确定性计量（`eval_benchmark.py`）

| 指标 | 宁德 | 江淮 |
| --- | ---: | ---: |
| 已计量输入 tokens | 537,055 | 873,136 |
| 修复与重试 / 模型尝试 | 2 / 7 | 2 / 7 |
| 综合分段接受 / 不可用 | 6 / 0 | 7 / 1 |
| 被假设引用的事实占比 | 11 / 174（6.3%） | 12 / 117（10.3%） |
| 挑战数 | 0 | 2 |
| 假设导向核查执行 / 固定证据检查 | 0 / 5 | 0 / 5 |

启动失败运行 `3149e2d5` 的模型尝试为 0，交付和用量均为未知，计入运行数，不记零分。

## 7. 边界与待用户抽查

- 分数来自单一评分者，主观。用户已抽查并同意两处：`h.2fabdb7a` 的 I=3，以及宁德的现金流遗漏算作严重错误。
- 旧策略基线只能和同一 rubric、同一公司、同一模型的新运行比较；F02 新契约尚无真实运行。
- 本次没有核心结论层面的独立加权分数；总体判断权重 3 的规则从下一轮评分开始使用，不回补本次分数。
- 稀疏样本和冲突证据目前只有数据采集或离线夹具，还没有可评分的完整运行。
