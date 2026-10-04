# 官方公告正文、经营披露明细与专项范围验收

Status: Historical

Do not use this document as evidence of current implementation behavior.

2026-10-03；批准设计基点 `8662cb8`，本地整合分支
`codex/research-data-integration-20261002`。当前运行语义见
[原生 API 运行说明](../../operations/evidence-research.md#official-document-admission)。

## 交付

- 新生产版本 v3 使用 DisclosureSources；已有 v1/v2 保留各自 collector、
  核心输入与提示语义。保存结果不重新取数/调模型，未知 dispatched 请求不重发。
- 优先沿 a-stock-data 的巨潮官方路线，原生接入最多一份正式年报/半年报和
  三份事件 PDF；官方目录、附件 ID/URL、证券及发行人、期间和大小/页数校验。
  pypdf 为 china 可选依赖。没有 OCR、模型表格抽取或隐藏 HTTP 重试。
- 正文保存有页码/哈希的摘录；经营表使用 Decimal、原始行/表头/单位和
  报告期。支持两种明确布局、跨页表头和换行标签；失败表不制造数值。
- 同一 PDF 的多个摘录和经营行共享公开 document family，不计作独立来源。
  经营表 family 不进入 C1 的封闭财务操作数集合。
- 全局来源覆盖、具体缺口与带 role 的专项待查分别保存、参与综合和展示。
  旧未知项标记范围未记录；可用维度不再收到错误的 missing-input 标签。
- 补充预算用尽保留此前合格材料；事件正文失败不降级已取得的经营表。
  取消、deadline 和 checkpoint 错误仍中止执行，不转成来源 fallback。

## 有限真实 PDF 探测与边界

探测在 `/tmp/tradingagents-body-collector-20261003/`，真实 PDF 下载通过
BudgetedSession 与 durable ledger，新增 **4 次 HTTP / 4 次文档 capability**，
取得公告 ID `1225495716`、`1225589532`、`1225570562`、`1225570561`。
身份、三表、日历和行情复用了上一轮合格探测缓存，**没有重新认证这些端点**。
没有调用模型或进行研究准确率评估。

首轮 live collector 记录 `run_20261003T104431490293Z_93e9e041`。
随后修正正文页选择，将经营表页优先于正文里的“部分产品”文字匹配，
重新解析已取得的原 PDF，并用缓存重放 collector（0 新 HTTP）：
`run_20261003T104957013927Z_adf4a134`。

最终三个模式均保存 **133 条代码生成事实、15 段正文摘录、24 条经营表记录**。
半年报摘录页为 **9、13、23、24、35**；第 23/24 页保存收入构成和成本/毛利表。
`announcement_bodies=partial`，理由为选中文档的有限摘录；
`operating_detail=qualified` 只说明已接纳的表记录通过资格，不代表全部经营信息。
原持仓论点和估值仍可能缺失，数据取得不等于整份研究充分。

## 检查

- 初轮针对性源/内核/model/C1/生产生命周期组合 **268 passed**。
- 后续来源族、页选择和读者报告组合 **163 passed**；最终补充隔离修复后的
  源解析、记录、研究、报告、发布及旧版恢复组合 **135 passed**。
  提交钩子要求的新测试格式与循环变量绑定修正后，受影响组合 **71 passed**。
  前后测试有重叠，不相加。
- 前端全量 **45 文件 / 327 tests passed**。npm ci、typecheck、production build
  通过；生成 static 随源码交付。验证为 Vitest/DOM，未执行新的原生浏览器验收。
- 全量离线 **3000 passed / 12 failed / 5 deselected / 73 subtests passed**，
  命令与原整合验收相同（关闭 dotenv，排除 smoke 与 paid DeepSeek live class）。
  12 项失败与既有基线同名：classic prefetch 三项、历史日期文本一项、
  runtime v2 预期三项、methodology 两项、Web CLI 日志权限三项。
  **全量 pytest 未全绿**；该次运行没有新增失败。全量运行在最终页选择、
  来源族与补充隔离修复之前；这些最终修复由上述 135 项针对性检查覆盖。
- Ruff、agent docs checker 与 diff whitespace 检查通过。npm 安装有既有
  16 项审计告警，build 有 >500 kB chunk 提示，未扩大为依赖升级/拆包。

## 明确限制

历史 cutoff 无已归档 PDF vintage 时不新接纳正文；未取得的正文保持可见。
布局不识别、缺单位、列错位和毛利计算不一致不会产生猜测行；可读摘录保留。
没有证明所有公司/所有报告模板可解析，没有付费全流程研究试跑，没有新增
浏览器截图或研究准确率对照。没有修改用户既有 run store、推送、PR、合并
或切换默认 profile。临时探测数据不是永久归档。
