"""Local terminal configuration for the current company-research workflow."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingagents.dataflows.ticker_utils import normalize_ticker_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.models import AnalysisRequest
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.decisions_client import DEFAULT_DECISION_MODEL, decision_run_config
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS, model_allowed
from tradingagents.llm_clients.stage_models import stage_model_overrides, stage_model_providers

DEFAULT_LOCAL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "tradingagents.local.json"

_LLM_KEYS = {"provider", "quick_think_llm", "deep_think_llm", "backend_url", "chatgpt_account_ref", "stage_models"}
_RUN_KEYS = {
    "ticker", "analysis_date", "research_question", "output_language", "evidence_search_enabled",
    "evidence_timeout_seconds", "evidence_source_vendors", "evidence_source_exclusions",
    "google_thinking_level", "openai_reasoning_effort", "anthropic_effort", "deepseek_thinking",
    "deepseek_reasoning_effort", "temperature", "llm_max_tokens",
    "jev_verification_enabled", "jev_model",
    "display_report",
}


def load_cli_config(path: str | Path | None = None) -> dict:
    """Load an optional local file; credential values remain in the process environment."""
    config_path = Path(path) if path else DEFAULT_LOCAL_CONFIG_PATH
    if not config_path.exists():
        if config_path == DEFAULT_LOCAL_CONFIG_PATH:
            return {}
        raise ValueError(f"配置文件不存在：{config_path}")
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("配置文件顶层必须是 JSON object。")
    keys = value.get("api_keys", {})
    if not isinstance(keys, dict) or any(not isinstance(v, str) for v in keys.values()):
        raise ValueError("api_keys 必须是环境变量名称到字符串的映射。")
    for name, secret in keys.items():
        if secret:
            os.environ[name] = secret
    return value


def build_request(
    local: dict,
    *,
    ticker: str | None = None,
    analysis_date: str | None = None,
    provider: str | None = None,
    quick_model: str | None = None,
    deep_model: str | None = None,
    language: str | None = None,
    focus: str | None = None,
) -> AnalysisRequest:
    """Resolve flags over JSON over environment-backed defaults at the CLI boundary."""
    unknown = local.keys() - {"api_keys", "llm", "run"}
    if unknown:
        raise ValueError(f"V9 不支持配置项：{', '.join(sorted(unknown))}")
    llm, run = local.get("llm", {}), local.get("run", {})
    if not isinstance(llm, dict) or not isinstance(run, dict):
        raise ValueError("llm 和 run 必须是 JSON object。")
    unknown = (llm.keys() - _LLM_KEYS) | (run.keys() - _RUN_KEYS)
    if unknown:
        raise ValueError(f"V9 不支持配置项：{', '.join(sorted(unknown))}")
    symbol = normalize_ticker_symbol(str(ticker or run.get("ticker") or "").strip())
    from tradingagents.research.native_evidence_policy import is_native_stock_ticker

    if not is_native_stock_ticker(symbol):
        raise ValueError("V9 公司研究仅支持 A 股普通股票，请输入如 002130、600519.SS 的代码。")
    config = deepcopy(DEFAULT_CONFIG)
    for key in _RUN_KEYS - {"ticker", "analysis_date", "research_question", "display_report"}:
        if key in run:
            config[key] = deepcopy(run[key])
    for key in _LLM_KEYS - {"provider"}:
        if key in llm:
            config[key] = llm[key]
    config["llm_provider"] = str(provider or llm.get("provider") or config["llm_provider"]).lower()
    if config["llm_provider"] not in {*PROVIDER_API_KEY_ENV, "chatgpt"}:
        raise ValueError(f"不支持的模型服务：{config['llm_provider']}")
    if config["llm_provider"] != DEFAULT_CONFIG["llm_provider"]:
        for key, flag, mode in (("quick_think_llm", quick_model, "quick"), ("deep_think_llm", deep_model, "deep")):
            if flag is None and key not in llm:
                options = MODEL_OPTIONS.get(config["llm_provider"], {}).get(mode, ())
                choices = [model for _, model in options if model != "custom"]
                if not choices:
                    raise ValueError(f"请为 {config['llm_provider']} 显式配置 {key}。")
                config[key] = choices[0]
    if quick_model is not None:
        config["quick_think_llm"] = quick_model
    if deep_model is not None:
        config["deep_think_llm"] = deep_model
    if language is not None:
        config["output_language"] = language
    for key in ("quick_think_llm", "deep_think_llm"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} 必须填写实际模型 ID。")
    selections = [(config["llm_provider"], config["quick_think_llm"], "quick", "quick_think_llm"),
                  (config["llm_provider"], config["deep_think_llm"], "deep", "deep_think_llm")]
    selections.extend((entry["provider"], entry["model"], None, f"stage_models.{key}.model")
                      for key, entry in stage_model_overrides(config).items())
    for selected_provider, model, mode, field in selections:
        if selected_provider != "chatgpt" and not model_allowed(selected_provider, model, mode):
            raise ValueError(f"{field} 不在 {selected_provider} 支持的模型目录中：{model}")
    if "chatgpt" in stage_model_providers(config) and not re.fullmatch(r"cg_[0-9a-f]{32}", str(config.get("chatgpt_account_ref", ""))):
        raise ValueError("请在 llm.chatgpt_account_ref 设置已登录的 ChatGPT 账户引用。")
    if config["output_language"] not in {"Chinese", "English"}:
        raise ValueError("output_language 必须是 Chinese 或 English。")
    config.update(decision_run_config(
        config.get("jev_verification_enabled"), config.get("jev_model", DEFAULT_DECISION_MODEL),
        configured=bool(os.environ.get(PROVIDER_API_KEY_ENV["openrouter"])),
    ))
    config.setdefault("evidence_timeout_seconds", 900)
    cutoff = analysis_date or run.get("analysis_date") or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if date.fromisoformat(cutoff) > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError("analysis_date 不能晚于当前日期。")
    return AnalysisRequest(
        ticker=symbol,
        analysis_date=cutoff,
        effective_config=config,
        research_question=focus if focus is not None else run.get("research_question"),
    )
