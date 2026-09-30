# T01 基线 manifest

- **状态：基线快照，2026-09-29 采集。** 本文件只记录**实测到的**环境事实。凡未实测的一律标注 `unknown` 或「未验证」，不写「应该可用」。
- 采集环境：agent A 的独立 worktree `.claude/worktrees/agent-a2d495cc50565c25e`。
- 复现命令见每节「复现」。本文不含任何密钥值、token 或带凭据的 URL。

## 0. 与设计/计划声明基线的差异（必须先解决）

| 来源 | 声明的代码基线 | 实际 |
| --- | --- | --- |
| 设计 §头 | `bc70a35580988de234b90520fbdf4b71373f012b` | 非本 worktree 的 HEAD |
| 任务计划 §头 | `bc70a35`，「执行前由 P0 的 T01 重新确认」 | 已重新确认，结果见下 |

**实测**：本 worktree `git rev-parse HEAD` = `a6a3f4c60f678c230a6290ed25c13a8da7a1431c`（2026-09-26，`Merge pull request #8 …codex/bilingual-readme`）。`main` 分支当前指向 `ca90f27c969fc6f27655f1475043e750d06daa2d`。

`a6a3f4c` 是 `ca90f27` 的祖先；两者之间的差异为：

| 提交 | 内容 |
| --- | --- |
| `a832ac3` / `bc70a35` | `.claude/settings.json`、`.codex/config.toml`、`.gitignore`、`CLAUDE.md`、`docs/README.md` |
| `ca90f27` | 新增 `docs/superpowers/specs/*`（设计 + 布局草图）、`docs/superpowers/plans/2026-09-29-catalyst-research-task-plan.md` |

**结论：落后的 2 个提交不含任何 `tradingagents/`、`cli/`、`frontend/` 产品代码。** 产品代码基线与 `bc70a35` 一致，因此 T01–T06 的代码结论对 `main` 同样成立。**但本 worktree 不含 `docs/superpowers/`**，所以本 agent 的交付目录需自建（已建）。合回时不会产生 spec 目录冲突。

**未验证**：`main` 上是否有其他 agent 的并行改动会在合回时移动 HEAD。合回前需重跑 `git rev-parse HEAD`。

## 1. 代码与平台

| 项 | 值 | 复现 |
| --- | --- | --- |
| HEAD | `a6a3f4c60f678c230a6290ed25c13a8da7a1431c` | `git rev-parse HEAD` |
| 分支 | `worktree-agent-a2d495cc50565c25e` | `git rev-parse --abbrev-ref HEAD` |
| 工作副本状态 | 干净（`git status --short` 无输出） | `git status --short` |
| 包版本 | `2.10.0`（`pyproject.toml`） | `grep -n '^version' pyproject.toml` |
| OS | macOS 27.0（Build 26A428），Darwin Kernel 27.0.0 | `sw_vers` / `uname -a` |
| 架构 | arm64（Apple Silicon，`Darwin … arm64`） | `uname -m` |
| Python | 3.13.13，conda env `tradingagents` | `python -V` |
| Node | v24.15.0（nvm） | `node -v` |
| npm | 11.12.1 | `npm -v` |
| 包总数（已装） | 173 | `pip freeze \| wc -l` |

**注意**：`AGENTS.md` 要求 Python 3.10+，实测 3.13.13 满足。仓库内 `.venv` **不存在**，符合项目记忆「用 conda 环境 `tradingagents`」。

## 2. 依赖版本（关键项）

`pip freeze` 摘录（`python -m pip freeze`）：

| 包 | 版本 |
| --- | --- |
| langchain-core | 1.3.2 |
| langchain-openai | 1.2.1 |
| langchain-anthropic | 1.4.2 |
| langchain-community | 0.4.1 |
| langgraph | 1.1.10 |
| langgraph-checkpoint | 4.0.3 |
| langgraph-checkpoint-sqlite | 3.0.3 |
| openai | 2.33.0 |
| anthropic | 0.97.0 |
| pydantic | 2.13.3 |
| fastapi | 0.139.2 |
| httpx | 0.28.1 |
| tenacity | 9.1.4 |
| tushare | 1.4.29 |
| akshare | 1.18.59 |
| mootdx | 0.11.7 |
| numpy | 2.4.4 |
| pandas | 3.0.2 |
| pytest | 9.0.3 |
| ruff | 0.15.20 |

`tenacity 9.1.4` 已安装 —— 对 T05（retry 审计）直接相关。

**未验证**：完整依赖树（173 项）未逐条抄录，也未执行 `npm --prefix frontend ci`（本 worktree 无 `frontend/node_modules`，且 T01–T06 不需要前端构建）。`package.json` / `package-lock.json` 中的前端依赖版本**未验证**。

## 3. 运行时模型与供应商（实测自既有 run，非本轮运行）

**本轮没有发起任何 LLM 调用或研究运行。** 以下全部来自 `~/.tradingagents/web/runs/` 中已完成 run 的事件日志。

| 项 | 值 | 来源 |
| --- | --- | --- |
| `llm_provider`（run.json） | `deepseek`（15/15 completed run 一致） | `run.json` |
| 事件层 `provider` 字段 | `openai`（309/309 调用） | `events.jsonl` `model.started.payload.provider` |
| 实际模型 ID | `deepseek-v4-flash`（255 次）、`deepseek-v4.1-flash-expires-on-0910`（50 次）、`deepseek-v4-pro`（4 次） | `events.jsonl` `model.started.payload.model` |

**⚠️ 命名陷阱（对 B agent 有直接影响）**：`run.json.llm_provider` 写 `deepseek`，而事件层 `provider` 写 `openai`。二者**不是矛盾**——本项目用 OpenAI 兼容协议端点接 DeepSeek 模型。因此**「provider」在两层含义不同**，新 policy/预算计数器必须明确以哪一层为准（见 T05 §4）。

`deepseek-v4.1-flash-expires-on-0910` 是带过期日的模型 ID，**已过期风险 unknown**，本轮未验证其可用性。

## 4. 有效配置摘要（无密钥）

来自 `run.json` 的 `metadata.effective_config`。只列与本次重构相关、且已实测存在的键：

| 键 | 值 | 与重构的关系 |
| --- | --- | --- |
| `analyst_concurrency_limit` | `1` | §5.4 建议新 profile 并发上限 2；当前为 1（串行） |
| `max_debate_rounds` | `1` | §3 称「默认多空轮数为 1」——**已确认** |
| `max_risk_discuss_rounds` | `1` | 旧风险辩论轮数 |
| `consistency_enabled` | `true` | 语义聚类路径开启 → T05 隐含调用来源 |
| `credibility_enabled` | `true` | 证据可信度门控 |
| `checkpoint_enabled` | `false` | 恢复路径在这些 run 中**未启用** |
| `a_share_news_official_fallback_enabled` | `true` | 公告 fallback 链 → T05 |
| `a_share_yfinance_min_coverage_ratio` | `0.6` | 项目记忆：A 股不用 yfinance |
| `akshare_adjust` | `""`（空） | 复权口径未配置 → T13 qfq |
| `bocha_*` 系列 | 已配置 | 新闻发现入口 |
| `credibility_domain_overrides` | `{}` | — |

`configured_keys`（哪些凭据**存在**，不含值）：`alpha_vantage`、`deepseek`、`fred`、`mimo`、`ollama`、`tavily`、`tushare` 为 `true`；`anthropic`、`azure`、`glm`、`glm-cn`、`google`、`minimax`、`minimax-cn`、`openai`、`openrouter`、`qwen`、`qwen-cn`、`xai` 为 `false`。

**注意 `openai: false` 而事件层 provider 为 `openai`** —— 再次印证第 3 节的命名分层，不是配置矛盾。

## 5. 环境变量键名（**只有键名，无值**）

代码引用的配置类键（`tradingagents/default_config.py`、`tradingagents/config.py`）：

```text
TRADINGAGENTS_ANTHROPIC_EFFORT          TRADINGAGENTS_LLM_MAX_RETRIES
TRADINGAGENTS_BENCHMARK_TICKER           TRADINGAGENTS_LLM_MAX_TOKENS
TRADINGAGENTS_CACHE_DIR                  TRADINGAGENTS_LLM_PROVIDER
TRADINGAGENTS_CHECKPOINT_ENABLED         TRADINGAGENTS_MAX_DEBATE_ROUNDS
TRADINGAGENTS_DEEP_THINK_LLM             TRADINGAGENTS_MAX_RISK_ROUNDS
TRADINGAGENTS_DEEPSEEK_REASONING_EFFORT  TRADINGAGENTS_MAX_TOOL_CALLS_PER_TURN
TRADINGAGENTS_DEEPSEEK_THINKING          TRADINGAGENTS_MAX_TOOL_MESSAGES_IN_CONTEXT
TRADINGAGENTS_EVIDENCE_GATE_ENABLED      TRADINGAGENTS_MEMORY_LOG_PATH
TRADINGAGENTS_EVIDENCE_STOP_ON_FAIL      TRADINGAGENTS_NEWS_LAYER1_ENABLED
TRADINGAGENTS_GOOGLE_THINKING_LEVEL      TRADINGAGENTS_NEWS_LAYER2_CACHE_DIR
TRADINGAGENTS_HALT_ON_MISSING_DATA       TRADINGAGENTS_NEWS_LAYER2_ENABLED
TRADINGAGENTS_LLM_BACKEND_URL            TRADINGAGENTS_NEWS_MIN_COMPANY_ITEMS
TRADINGAGENTS_OUTPUT_LANGUAGE            TRADINGAGENTS_NEWS_MIN_MIXED_ITEMS
TRADINGAGENTS_QUICK_THINK_LLM            TRADINGAGENTS_RESULTS_DIR
TRADINGAGENTS_TEMPERATURE                TRADINGAGENTS_WIND_ENABLED
TRADINGAGENTS_WIND_MAX_CONCURRENCY       TRADINGAGENTS_WIND_REQUEST_TIMEOUT_SECONDS
TRADINGAGENTS_WIND_STRICT_EDB_ALLOWLIST
```

凭据类键名（**本文件只列名字，不列任何值**）：

```text
ALPHA_VANTAGE_API_KEY   ANTHROPIC_API_KEY      AZURE_OPENAI_API_KEY
BOCHA_API_KEY            DASHSCOPE_API_KEY      DASHSCOPE_CN_API_KEY
DEEPSEEK_API_KEY         DOUBAO_SEARCH_API_KEY  FRED_API_KEY
GOOGLE_API_KEY           MIMO_API_KEY           MINIMAX_API_KEY
MINIMAX_CN_API_KEY       OPENAI_API_KEY         OPENROUTER_API_KEY
TAVILY_API_KEY           TUSHARE_API_KEY        WIND_API_KEY
XAI_API_KEY              ZHIPU_API_KEY          ZHIPU_CN_API_KEY
```

其他：`AZURE_OPENAI_DEPLOYMENT_NAME`、`OLLAMA_BASE_URL`、`TQDM_DISABLE`。

**本 worktree 内 `.env` 与 `tradingagents.local.json` 均不存在**（`ls` 报 No such file）。真实凭据在主 checkout 的忽略文件中，本 agent 未读取、未复制、未记录其值。

**`TRADINGAGENTS_LLM_MAX_RETRIES` 存在** —— 这是 T05「SDK retry 是否纳入预算」的直接配置入口。

## 6. 已有失败测试清单

**采集方式**：`python -m pytest --collect-only -q`

**⚠️ 状态：`unknown`（本轮未完成采集）。** collect 超过 120s 被转入后台，agent 交付前未取得终态。因此**本文不写「基线无失败测试」**——那正是设计 §15 反复警告的不可判定表述。

**可复现命令**（由 G agent 或合回后的主会话执行）：

```bash
cd /Users/david/codespace/TradingAgents
conda run -n tradingagents python -m pytest --collect-only -q 2>&1 | tail -20
conda run -n tradingagents python -m pytest -q 2>&1 | tail -40
```

**判读规则（交给 G）**：区分「本次回归」与「基线既有失败」时，只认上面前一条命令的实际输出，不得引用本节的空缺。

`npm --prefix frontend run test` / `test:e2e` / `typecheck` / `build` **本轮全部未执行**（本 agent 不改前端，且 worktree 无 `node_modules`）。基线状态 = `unknown`。

## 7. 用户数据（只读确认，未修改）

| 路径 | 内容 | 本 agent 操作 |
| --- | --- | --- |
| `~/.tradingagents/web/runs/` | 26 个条目：25 个 run + 1 个 `batches` | **只读** |
| ├─ completed | 15 | 读取 |
| ├─ failed | 7 | 读取（用于找 `unknown` usage） |
| ├─ cancelled | 3 | 读取 |
| `~/.tradingagents/cache/` | 78 个条目 | 未触碰 |
| `~/.tradingagents/logs/` | 45 个条目 | 未触碰 |
| `~/.tradingagents/memory/` | 1 个条目 | 未触碰 |

**没有任何文件被创建、修改或删除。** 全部探针脚本写在 `/tmp/ta_probe/`。

完成 run 的 ticker：`002130.SZ`、`002335.SZ`、`002249.SZ`、`002223.SZ`、`600580.SS`、`605277.SS`、`002185.SZ`（+ 8 个 run 的 `company_name` 字段为空，只有 `batch_input`）。

## 8. 供后续 agent 使用的 policy 版本事实（已核验）

```text
tradingagents/research/horizon_policy.py:23
    POLICY_VERSION = "horizon-policy-v2"

tradingagents/runtime/contracts.py:8
    RuntimePolicyVersion = Literal["horizon-policy-v2", "horizon-policy-v3"]
```

**`horizon-policy-v3` 是已激活的测试门控策略，不是新 catalyst policy 的命名目标。**

`RuntimePolicyVersion` 的消费点**实测为 5 个文件、约 20 处**（比任务计划 §3 写的「四处」更多）：

| 文件 | 处数 |
| --- | --- |
| `tradingagents/runtime/reconciliation.py` | 15（`24, 74, 118, 255, 336, 483, 545, 688, 730, 794, 836, 867, 915` 等） |
| `tradingagents/web/manager.py` | 2（`41, 1536`） |
| `tradingagents/runtime/fingerprint.py` | 已 import（见 T05） |
| `tradingagents/execution/runner.py` | 已 import（见 T05） |
| `tradingagents/observability/canonical.py` | 已 import（见 T05） |

→ **`catalyst-evidence-policy-v1` 禁止加入该 Literal。** 详见 T05 §5 与 T06 §7。

## 9. 本 manifest 的自检

- [x] `git rev-parse HEAD` 与 §1 一致（`a6a3f4c60f678c230a6290ed25c13a8da7a1431c`）
- [x] 无 `sk-` 前缀
- [x] 无 16 位以上疑似 token 字面量（所有 sha 为 40 位且标注为 git commit）
- [x] 无带 token 的 URL（全文无 URL）
- [x] 无任何环境变量**值**、无 API key 值
- [x] 缺失项一律标 `unknown` / 「未验证」，无「应该可用」
