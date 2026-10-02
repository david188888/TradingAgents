# 证据驱动研究：首批基础层验收记录

Status: Historical — 2026-09-30 本地实施记录，未发布。

Do not use this document as evidence of current implementation behavior.

对应[实施计划 A 批](2026-09-30-evidence-driven-research-implementation.md)。用户已认可阅读样稿并确认 Wind、Tushare、a-stock-data 为现有来源。本记录只覆盖数据和确定性计算，不代表统一研究内核、正式 Reader 或判断质量已经验收。

## 本地改动

- Wind CLI 2.0.4 契约：平铺错误类型、当前 EDB 搜索/查询名称和载荷、明确 `afdate` 复权锚点。原串行、超时、供应商顺序和模型预算保留。
- bounded Tushare 价格适配：REST 日行情/因子/交易日历经过现有许可和 HTTP 账本；按配置选择首个有界适配，Wind-only 不替换。核查身份、日期、OHLC、逐日因子、锚点和缺行。历史检索不证明当时 factor vintage，保持 unavailable。
- 修正初始峰值回撤与缺失日跨期收益；代码计算单标的波动率、带符号历史 VaR/ES、尾样本和 Wilder ATR。缺基准不取消单标的计算，缺 OHLC 不取消 close-based 风险。
- 计算结果附在合格价格证据中，先冻结/持久化再供市场专项读取。尚未发布独立量化 case/Reader 投影。

## 真实数据探测（非 LLM 研究）

样本 `600519.SH`，窗口 `2026-08-24..2026-08-28`。

| 来源/接口 | 观察 |
| --- | --- |
| Wind `get_stock_kline`, aftype=0, afdate=2026-08-28 | 成功取得 5 条 OHLC；证明该次行情请求可用，不证明其他接口权限。 |
| Tushare `daily`, `adj_factor`, `trade_cal` | 各 HTTP 200 / vendor code 0 / 5 条；代码规范化得到完整 5 个交易日、锚点 2026-08-28。 |
| Tencent qfq（a-stock-data 对应能力） | 5 条，window_covered=true，但 pit_status=unverified；不升为历史合格证据。 |

Tushare 规范化输入 hash：`767b358130251bf17b03c22664f1f48fc58e3d31e7f6ff2dadaac2dad665bb1d`。capture 在历史窗口之后，正确输出 `historical_factor_vintage_unverified`。只记录响应元信息，不记录 credentials。没有运行付费 LLM，也未扩大订阅、额度或数据授权。当前 cutoff 的完整真实 case、财报权限及新 EDB 路由真实取数不在这份验收中。

## 离线检查

```bash
python -m pytest tests/test_price_statistics_context.py tests/test_tushare_price_qualification.py tests/test_risk_metrics_integrity.py tests/test_wind_current_contract.py tests/test_index_and_risk_metrics_local.py tests/test_wind_provider.py tests/web/test_catalyst_production_wiring.py -m 'not smoke' -q --color=no
ruff check tradingagents cli scripts/check_agent_docs.py
ruff check tests/test_tushare_price_qualification.py tests/test_risk_metrics_integrity.py tests/test_price_statistics_context.py tests/test_wind_current_contract.py tests/test_wind_provider.py
python scripts/check_agent_docs.py
git diff --check
```

结果：166 passed，4 个 live smoke deselected；Ruff、文档检查（57 页）、diff whitespace 均通过。上述命令实际通过 `rtk` 执行。检查范围包括手算反例、输入污染、权限失败、分指标退化、真实 REST 适配的 4 次 HTTP/4 次能力扣账及恢复消耗，以及现有执行/持久化/投影测试。极值溢出反例产生预期 pandas warning 后拒绝非有限统计值；已有 Starlette/httpx 弃用 warning 未改。

未修改生产前端，因此没有用 mockup 浏览器验收冒充正式 Reader 测试，也未触发前端重建。没有提交、推送或删除用户数据。

## 下一依赖

B/C/D 批仍需完成版本化证据摘录/假设/验证/判断契约、三模式共用执行及 Reader 投影。当前计算接入仅服务 bounded 价格证据，不代表 classic/company/holding 已迁移。准确性提升需固定证据对照和真实研究人工验收。
