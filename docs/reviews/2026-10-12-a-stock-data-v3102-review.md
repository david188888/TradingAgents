# a-stock-data v3.10.2 选择性同步审查

Status: Investigation

## 固定版本与差异

用户于 2026-10-12 授权选择性合并本次上游更新，并随 TradingAgents 新版本发布。
对照 [v3.10.2 Release](https://github.com/simonlin1212/a-stock-data/releases/tag/v3.10.2)
与 GitHub 固定 tag 比较：基线 v3.10.1 为 `8f6a6a53a59813bf5f010875f16f794fdc4f44f4`，
目标 v3.10.2 为 `29b07d2e37005b9fd568bca1262f6e572b5f9407`，不使用浮动 main。
变更文件为 SKILL.md、README.md、README_en.md、CHANGELOG.md 与新增 tests/test_valuation.py。

## 适用性与决定

唯一计算修复是 #58：`full_valuation()` 改为复用 `pe_digestion()`。
当前 EPS 缺失或非正，或前向 PE 高于 30x 但下一年 EPS 缺失、持平或下降时，
`digest_years` 从误导的 0 改为 None；批量打印显示“无法估算”。
正 EPS 且 PE 不高于 30x 的 0，以及正增长时的有限年数保持原语义。

本仓库只手写移植所需的 A 股适配器，没有 import 上游 skill。
对 tradingagents、frontend/src 与 tests 搜索上述函数和结果字段，无运行实现或消费者：

- `dataflows/native_valuation.py` 读取腾讯 PE/PB 快照和 tushare 历史倍数，缺失倍数保留 None。
- `research/native_valuation.py` 从冻结证据组装估值；没有快照时不生成判断，缺失锚不填零。
- `dataflows/minimum_sources.py` 的机构 EPS 与行业候选只是有日期的上下文，不作为新的公平价值锚。
- `research/valuation.py` 使用显式情景与输入资格，不计算固定 30x 的消化年数。

因此本次选择性同步仅纳入固定版本的适用性审查与能力文档更新，**没有适用的适配器代码需要合并**。
不新增无消费者的 PE 消化功能，不把上游 30x 假设引入公司价值判断；若未来引入，
必须区分“已达假设阈值的 0 年”与“无法估算的 None”，并验证缺失、零、负 EPS 和非正增长。
此前 v3.10.1 的腾讯股票成交量单位修复继续保留。

## 验证范围

本地估值、机构 EPS 和腾讯单位相关的现有离线回归随发布检查执行，结果见
[v3.3.1 发布记录](2026-10-12-v3.3.1-release-notes.md)。没有运行上游付费或联网取数，
不改外部 Proma/global skill，不重写历史证据与用户运行数据。
