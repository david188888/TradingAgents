# a-stock-data v3.10.1 最小修复与 Proma 升级验收

Status: Verification record

用户于 2026-10-07 确认：先做 TradingAgents 最小修复与 Proma 原样升级，不做按需加载结构改造。
审查依据见 [版本审查](2026-10-07-a-stock-data-v3101-review.md) 与 [Proma 审查](2026-10-07-proma-a-stock-data-v3101-review.md)。

## TradingAgents 已交付

- 本地分支 `codex/a-stock-data-v3101-20261007`，基线 `033c7bb8`；保留此前未提交审查文档。
- 腾讯日/周/月 × raw/qfq 的科创板股票（归一化腾讯代码 sh688/sh689）标为 `shares`；其他研究范围内股票继续标为 `lots (100 shares)`。
- 原始 Volume 数值不变。文本报告从同一 provenance 读取单位，消除独立硬编码。
- 单位规则不推广为可转债、指数或 ETF 的完整品种政策；不新增这些研究能力。
- 补充普通股票日线整手取整、周/月加总的限制；当前能力文档记录仅采纳 v3.10.1 的相关单位修正。
- 不改公共 schema、供应商选择、复权/PIT 资格、预算、旧运行/缓存、证据哈希或用户数据。
- 不涉及前端源码或生成静态资源。

## TradingAgents 验证

新增 42 个参数组合：688981、689009、聚宽/前缀输入、沪深主板与创业板，覆盖三个周期和两个价格口径。
每项同时断言来源单位、规范化代码、未换算的原始 Volume 及文本报告。
修复前结果：24 failed / 18 passed；失败均为科创板单位错误。

修复后：

```bash
PYTHON_DOTENV_DISABLED=1 python -m pytest -q -p no:randomly --color=no \
  tests/test_tencent_kline_tdx2.py tests/test_tencent_kline_periods.py \
  tests/test_tencent_kline_t13.py tests/test_native_multisource.py \
  tests/test_native_valuation.py
ruff check tradingagents cli scripts/check_agent_docs.py tests/test_tencent_kline_tdx2.py
python scripts/check_agent_docs.py
git diff --check
```

结果：120 passed，Ruff 与文档检查通过，diff 无空白错误。
这是针对本次更改的离线回归，不是全套测试、独立跨源成交量实测或研究准确率证明。

## Proma 升级

由用户已授权的 subagent 在目标目录原样实施，详见 [Proma 升级验收](2026-10-07-proma-a-stock-data-v3101-acceptance.md)。

- 目标 HEAD 为固定 `v3.10.1` / `8f6a6a53a59813bf5f010875f16f794fdc4f44f4`，工作树干净，使用 detached HEAD；旧 main 指针保留。
- 主会话另用独立下载的固定 tag 对照：15 个 tracked 文件清单一致，逐文件 SHA256 零差异。
- 升级前含 `.git` 的完整 51 文件备份实际解包比对通过；唯一未提交 SKILL.md 同时保存在 stash，未删除或 pop。
- 耐久备份与恢复快照定位保存在本机私有验收记录，公开版本不包含个人工作区路径或 stash 定位。
- 升级后的目标目录运行 upstream unittest：173 passed / 4 skipped；测试解释器为现有 Miniconda Python 3.13.5，没有安装或修改依赖。
- subagent 直接加载目标 SKILL 中的实现做免费联网 smoke，2026-09-30 腾讯日 K 与通达信官网盘后包对账：688981 按股差 0，588000/600519/000001 按 100 股或份换算差 −32/+2/−45，均在一个手的取整差内。
- 未做按需加载改造、未修改 Proma 投资手册/研究产出/缓存/记忆。Proma 实际会话解释器及已打开会话重新加载状态未验证，磁盘更新不能证明这两项。

## 发布状态

上述实施验收时仅有本地改动。随后用户明确授权提交、推送、PR 合并与新版本发布；本次版本为 TradingAgents v3.1.0，见 [发布说明](2026-10-07-v3.1-release-notes.md)。GitHub 实际发布状态以远端 PR、tag 与 Release 为准。Proma 的保存对象仅用于本地恢复，不向其上游推送。按需加载优化留待另行确认。

## v3.1.0 发布前检查

基于已合并的主分支 `5944f6f`，同步 Python、frontend package 与 lock 根版本为 3.1.0。
本次重新执行的扩大定向后端套件（来源、原生估值、V5 核查、V6 focus、Reader process、DeepSeek 与环境覆盖）286 项通过；不是全量 pytest。
前端 `npm ci`、typecheck/build 通过，全量 Vitest 330 项通过。
Playwright 全部 20 项通过；初次沙盒启动被 macOS Mach port 权限阻止，获准环境下重跑后通过，未更改测试或放宽断言。
Ruff、文档链接检查与 diff 空白检查通过；重新构建后的 tracked SPA 内容无变化。
sdist/wheel 构建成功，wheel metadata 及前端三处版本均核对为 3.1.0；wheel 中包含单位修复。发布沿用 GitHub 源码 Release，未上传本机构建产物或 Proma 私有资料。

`npm audit` 报告现有依赖 18 项（4 moderate、12 high、2 critical），critical 涉及 Vitest/tinypool 测试依赖；本次 package-lock 只改根版本号，未改依赖解析或执行自动修复。该审计不记为通过，需单独处理。
构建仍有既有的大 chunk 提示。GitHub 当次核查为 0 Actions workflow、无分支保护或 ruleset；无必需 CI/review，不把缺失检查写成 CI 成功。
