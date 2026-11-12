# CLI company research

Status: Current

CLI and Web execute the same V9 Insight workflow. Only A-share common stocks and company research are supported. Older multi/bear debate, catalyst executors and V1–V8 reading/recovery are removed; user files are never migrated or deleted automatically.

```bash
conda activate tradingagents
tradingagents analyze --ticker 002130 --show
tradingagents analyze --ticker 600519 --focus "经营现金流是否支持利润增长？" --output report.md
tradingagents analyze --resume RUN_ID
```

The default cutoff is today's Asia/Shanghai date. `--date YYYY-MM-DD` explicitly sets the research cutoff. `--provider`, `--quick-model`, `--deep-model` and `--language Chinese|English` override local JSON, which overrides environment-backed defaults. Selecting another provider selects that provider's catalog defaults when available; providers without catalog defaults require explicit model IDs.

`--config path.json` reads local credentials from `api_keys` into process environment only. See the root `tradingagents.config.example.json`. The `llm` object configures provider, model IDs, backend URL, optional `chatgpt_account_ref` and optional `stage_models`; `run` configures ticker/date/focus, language, thinking options, source configuration and search enablement. Old analysts/depth/trading configuration and ineffective `save_report`/`llm_max_retries` switches are rejected rather than silently ignored. Reports are always saved and V9 controls retries through durable attempt budgets. ChatGPT uses an already authorized local account reference from the Web account flow.

`llm.stage_models` routes stages to different models so one model's perspective does not dominate. Keys are `specialist`, `challenge`, `synthesis`, `focus_response` and the roles `operating_quality`, `event_context`, `market_context`; a role overrides `specialist`, responses follow their specialist, and unset stages keep `quick_think_llm` (synthesis: `deep_think_llm`). Each entry takes `provider`, `model` and optional `effort`; a stage on another provider uses that provider's default endpoint, and every selected provider's key is checked before dispatch.
Saved runs that used `run.deepseek_task_efforts` retain those settings on resume.

```json
"stage_models": {
  "specialist": {"provider": "deepseek", "model": "deepseek-flash"},
  "challenge": {"provider": "anthropic", "model": "claude-opus-4-8", "effort": "high"},
  "synthesis": {"provider": "openai", "model": "gpt-5.6"}
}
```

Every run saves attempts, evidence, stage results, canonical Insight report and Markdown under `~/.tradingagents/cli/runs/`. `--run-dir` selects another CLI store. CLI holds an exclusive writer lock separately from the Web store, so both adapters may operate concurrently without sharing a writer. `--output` makes an additional Markdown export; `--show` displays it in the terminal. Saved reports are always persisted as part of completion.

Ctrl+C records interruption. Resume reuses the saved request and spent budgets. Unknown dispatched outcomes stay spent; resume never upgrades a request or repeats an unknown attempt. Use the original local provider credentials; endpoint credentials are reattached at runtime only when the endpoint's semantic identity matches. Completed resume only verifies and reads the committed report. A partial report may preserve usable research while withholding its overall rating.

Configuration failures exit before model/data dispatch. Execution failures remain failures with saved state; publication must pass its durable authorization barrier and produce the canonical report before completion is announced. No CLI invocation clears historical data or checkpoints.
