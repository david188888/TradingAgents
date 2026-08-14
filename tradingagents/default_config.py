import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    "TRADINGAGENTS_MAX_TOOL_CALLS_PER_TURN": "max_tool_calls_per_turn",
    "TRADINGAGENTS_MAX_TOOL_MESSAGES_IN_CONTEXT": "max_tool_messages_in_context",
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
    "TRADINGAGENTS_EVIDENCE_GATE_ENABLED":   "evidence_gate_enabled",
    "TRADINGAGENTS_EVIDENCE_STOP_ON_FAIL":   "evidence_stop_on_fail",
    "TRADINGAGENTS_NEWS_MIN_COMPANY_ITEMS":  "news_min_company_items",
    "TRADINGAGENTS_NEWS_MIN_MIXED_ITEMS":    "news_min_mixed_items",
    "TRADINGAGENTS_HALT_ON_MISSING_DATA":    "halt_on_missing_data",
    "TRADINGAGENTS_NEWS_LAYER1_ENABLED":     "news_layer1_enabled",
    "TRADINGAGENTS_NEWS_LAYER2_ENABLED":     "news_layer2_enabled",
    "TRADINGAGENTS_NEWS_LAYER2_CACHE_DIR":   "news_layer2_cache_dir",
    "TRADINGAGENTS_WIND_ENABLED":            "wind_enabled",
    "TRADINGAGENTS_WIND_MAX_CONCURRENCY":    "wind_max_concurrency",
    "TRADINGAGENTS_WIND_REQUEST_TIMEOUT_SECONDS": "wind_request_timeout_seconds",
    "TRADINGAGENTS_WIND_STRICT_EDB_ALLOWLIST": "wind_strict_edb_allowlist",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value.

    Invalid values raise ValueError rather than silently falling back.
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    # This fork is A-share-first and defaults to DeepSeek (no OpenAI key needed).
    # Override per-environment via TRADINGAGENTS_LLM_PROVIDER / TRADINGAGENTS_*_LLM.
    "llm_provider": "deepseek",
    "deep_think_llm": "deepseek-v4-pro",
    "quick_think_llm": "deepseek-v4-flash",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Sampling temperature forwarded to every provider when set. None leaves
    # each provider at its own default.
    "temperature": None,
    # SDK retry budget forwarded to every provider chat client. None leaves
    # each provider/SDK at its own default (usually 2).
    "llm_max_retries": None,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "Chinese",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Hard upper bound for one model response.  It prevents a malformed or
    # over-eager model from expanding one analyst turn into an unbounded tool
    # batch; callers retain the first calls in their declared order.
    "max_tool_calls_per_turn": 8,
    # Retain only the newest tool-result messages after each tool task.  The
    # current result batch always survives; older results can be re-fetched
    # from durable tool observations instead of inflating the next prompt.
    "max_tool_messages_in_context": 8,
    "analyst_concurrency_limit": 1,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,
    "global_news_article_limit": 10,
    "global_news_lookback_days": 7,
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "mootdx,yfinance,tushare,akshare,alpha_vantage",  # Options: mootdx, yfinance, tushare, akshare, alpha_vantage (mootdx = A-share only, TCP 7709 no IP ban; akshare removed from the runtime chain but kept in config so an explicit override stays valid)
        "technical_indicators": "local,yfinance",  # Options: local (A-share stockstats over mootdx/tushare), alpha_vantage, yfinance
        "fundamental_data": "tushare,akshare,alpha_vantage",  # A-share fundamentals: Tushare -> AKShare; Sina is used only for the three statements below
        "news_data": "tavily,eastmoney,yfinance,alpha_vantage",  # Options: tavily, eastmoney (A-share keyless), alpha_vantage, yfinance
        "macro_data": "fred",                # Options: fred (needs FRED_API_KEY)
        # Optional A-share research supplements.  Their failures degrade to a
        # source-labelled unavailable result and do not affect core OHLCV.
        # ths serves aggregate northbound flow (get_a_share_northbound_flow);
        # it is skipped automatically for the other methods in this category.
        "a_share_market_data": "ths,eastmoney,china_exchange",
        "a_share_valuation": "tencent",
        "a_share_research": "eastmoney,ths",
        "a_share_company_data": "mootdx",
        "a_share_official_data": "cninfo,china_exchange",
        "a_share_options": "sina",
        "a_share_sentiment": "ths,eastmoney",
        # These source records are optional supplements for A-share research;
        # they are intentionally separate from core OHLCV/fundamentals.
        "china_macro_data": "akshare",
        "a_share_specialty_data": "eastmoney",
        "a_share_query_data": "iwencai",
        "a_share_telegraph": "cls",
        # Wind AIFin Market is the premium primary; EastMoney is the keyless
        # fallback for index snapshot/history when Wind is unavailable.
        "wind_index_data": "wind,eastmoney",
        "wind_macro_data": "wind",
        "wind_risk_data": "wind",
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # The three A-share statements drop the akshare wrapper in favor of the
        # Sina direct endpoint (quotes.sina.cn, zero key); tushare remains the
        # primary A-share statement source.  Non-A-share tickers skip tushare/
        # sina via the market matrix and fall through to yfinance/alpha_vantage.
        "get_balance_sheet": "tushare,sina,yfinance,alpha_vantage",
        "get_cashflow": "tushare,sina,yfinance,alpha_vantage",
        "get_income_statement": "tushare,sina,yfinance,alpha_vantage",
        # A-share indicators are computed locally from the mootdx/tushare OHLCV
        # chain; non-A-share tickers skip "local" and use yfinance.
        "get_indicators": "local,yfinance",
        # Historical trend analysis must never fall back to raw OHLCV.
        "get_adjusted_price_history": "wind,tushare,akshare,yfinance,alpha_vantage",
        # News uses one shared company-news chain; the router filters vendors
        # by market. Global news has its own method-compatible chain.
        "get_news": "tavily,eastmoney,yfinance,alpha_vantage",
        "get_global_news": "tavily,yfinance,alpha_vantage",
        # Interactive Q&A is registered in the broad specialty category, whose
        # default is EastMoney; pin these two AKShare-only methods explicitly.
        "get_a_share_interactive_questions": "akshare",
        "get_a_share_interactive_answers": "akshare",
    },
    # Tavily news search controls. Defaults intentionally keep API usage low.
    "halt_on_missing_data": True,
    "a_share_yfinance_min_coverage_ratio": 0.6,
    "a_share_yfinance_min_rows": 3,
    "a_share_yfinance_min_fundamental_fields": 5,
    "akshare_adjust": "",
    "tavily_search_depth": "basic",
    "tavily_max_results": 5,
    "tavily_topic": "news",
    "tavily_company_news_topic": "news",
    "tavily_company_fallback_topic": "finance",
    "tavily_global_news_topic": "news",
    "tavily_global_fallback_topic": "finance",
    "tavily_min_score": None,
    "tavily_include_raw_content": False,
    "tavily_include_answer": False,
    "tavily_include_images": False,
    "tavily_auto_parameters": False,
    "tavily_company_news_query_template": (
        '"{ticker}" "{company_name}" stock market news earnings revenue guidance analyst rating'
    ),
    "tavily_a_share_news_query_template": (
        '"{ticker}" "{plain_ticker}" "{company_name}" 股票 公告 业绩 财报 经营 舆情 市场 新闻'
    ),
    "tavily_global_news_query": (
        "global financial markets macro economy central bank inflation monetary policy "
        "earnings commodities geopolitical risk"
    ),
    "tavily_include_domains": [],
    "tavily_exclude_domains": [],
    "tavily_company_include_domains": [],
    "tavily_company_exclude_domains": [],
    "tavily_global_include_domains": [],
    "tavily_global_exclude_domains": [],
    # When ordinary company-news providers cannot return A-share coverage,
    # query the existing public SSE/SZSE announcement adapter as a clearly
    # labelled source-priority fallback.  It is not used for global news and
    # is never a silent substitute when ordinary news already succeeded.
    "a_share_news_official_fallback_enabled": True,
    "news_curator_max_items": 10,
    # A-share sentiment analyst: include the dragon-tiger list (短线资金活跃度)
    # as an optional sentiment block. Disable for a longer-horizon read where
    # short-term hot-money signals are noise.
    "sentiment_a_share_dragon_tiger_enabled": True,
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",       # NSE India (Nifty 50)
        ".BO":  "^BSESN",      # BSE India (Sensex)
        ".T":   "^N225",       # Tokyo (Nikkei 225)
        ".HK":  "^HSI",        # Hong Kong (Hang Seng)
        ".L":   "^FTSE",       # London (FTSE 100)
        ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
        ".AX":  "^AXJO",       # Australia (ASX 200)
        ".SS":  "000001.SS",   # Shanghai (SSE Composite)
        ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
        "":     "SPY",         # default for US-listed tickers (no suffix)
    },
    # Evidence gate configuration
    "evidence_gate_enabled": True,
    "evidence_max_enrichment_rounds": 3,
    "evidence_max_enrichment_seconds": 90,
    "news_min_company_items": 3,
    "news_min_mixed_items": 5,
    "evidence_stop_on_fail": False,
    # Credibility scoring for news sources
    "credibility_enabled": True,
    "credibility_domain_overrides": {},
    # Cross-source consistency detection
    "consistency_enabled": True,
    # Identity verification: additional known confusing company names
    "wrong_identity_hints": [],
    # News advisor (LLM-based coverage gap analysis + targeted search)
    "news_advisor_enabled": True,
    # Cost-aware news-analysis runtime.  The Layer 0/1/2 contracts are always
    # available, but model calls are explicit opt-ins: deployments without an
    # LLM or batch provider keep the ordinary advisor/rule-based behavior.
    "news_layer1_enabled": False,
    "news_layer1_max_items": 50,
    "news_layer2_enabled": False,
    "news_layer2_cache_dir": os.getenv(
        "TRADINGAGENTS_NEWS_LAYER2_CACHE_DIR",
        os.path.join(_TRADINGAGENTS_HOME, "cache", "news-layer2"),
    ),
    # Wind AIFin Market (https://aifinmarket.wind.com.cn) premium data.
    # Enabled by default for this local research workspace. Set
    # wind_enabled=False to disable Wind capabilities without affecting core
    # A-share OHLCV/fundamentals/news paths.
    "wind_enabled": True,
    "wind_max_concurrency": 1,
    "wind_request_timeout_seconds": 120,
    "wind_strict_edb_allowlist": False,
    "wind_pinned_skill_version": "2.0.1",
    # Methodology scorecards deliberately keep subjective cutoffs in config,
    # rather than burying them in a skill prompt. They are interpretation aids,
    # not trading rules: missing inputs must remain unavailable.
    "methodology_thresholds": {
        "fundamentals": {
            "altman_z_distress": 1.8,
            "altman_z_safe": 3.0,
            "beneish_m_manipulation": -1.78,
        },
        "market": {
            "health_score_weak": 40.0,
            "health_score_strong": 70.0,
        },
        "sentiment": {
            "retail_bullish_overextension": 0.90,
            "retail_bullish_balance": 0.70,
            "reality_gap_material": 25.0,
        },
    },
})


def validate_config(config: dict) -> list[str]:
    """Return a list of configuration problems; [] means the config is usable.

    Structural checks only: provider/model presence, positive round counts,
    boolean switches and numeric knobs. Vendor names are validated separately
    by ``dataflows.registry.validate_data_vendors``; model existence is left to
    the LLM client layer.
    """
    problems: list[str] = []
    provider = str(config.get("llm_provider", "")).strip().lower()
    if not provider:
        problems.append("llm_provider is required")
    for key in ("deep_think_llm", "quick_think_llm"):
        if not str(config.get(key, "")).strip():
            problems.append(f"{key} is required")
    for key in ("max_debate_rounds", "max_risk_discuss_rounds", "max_recur_limit"):
        try:
            if int(config.get(key, 0)) < 1:
                problems.append(f"{key} must be a positive integer")
        except (TypeError, ValueError):
            problems.append(f"{key} must be an integer, got {config.get(key)!r}")
    for key in (
        "checkpoint_enabled",
        "halt_on_missing_data",
        "evidence_gate_enabled",
        "evidence_stop_on_fail",
    ):
        if not isinstance(config.get(key), bool):
            problems.append(f"{key} must be a boolean, got {config.get(key)!r}")
    temperature = config.get("temperature")
    if temperature is not None and temperature != "":
        try:
            float(temperature)
        except (TypeError, ValueError):
            problems.append(f"temperature must be numeric, got {temperature!r}")
    for key in (
        "max_tool_calls_per_turn",
        "max_tool_messages_in_context",
        "llm_max_retries",
    ):
        value = config.get(key)
        if value is None or value == "":
            continue
        try:
            if int(value) < 0:
                problems.append(f"{key} must be non-negative")
        except (TypeError, ValueError):
            problems.append(f"{key} must be an integer, got {value!r}")
    return problems
