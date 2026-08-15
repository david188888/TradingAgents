import copy
import datetime
import os
import sys
import time
from functools import wraps
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich import box
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=True)
load_dotenv(PROJECT_ROOT / ".env.enterprise", override=False)

from cli.announcements import display_announcements, fetch_announcements
from cli.config import (
    DEFAULT_LOCAL_CONFIG_PATH,
    build_configured_selections,
    load_cli_config,
)
from cli.run_observer import CliRunObserver
from cli.stats_handler import StatsCallbackHandler
from cli.utils import (
    ask_anthropic_effort,
    ask_deepseek_effort,
    ask_deepseek_thinking,
    ask_gemini_thinking_config,
    ask_glm_region,
    ask_minimax_region,
    ask_openai_reasoning_effort,
    ask_output_language,
    ask_qwen_region,
    confirm_ollama_endpoint,
    detect_asset_type,
    ensure_api_key,
    get_ticker,
    resolve_backend_url,
    select_analysts,
    select_deep_thinking_agent,
    select_llm_provider,
    select_research_depth,
    select_shallow_thinking_agent,
)
from tradingagents.dataflows.progress import progress_sink
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.models import AnalysisRequest
from tradingagents.graph.analyst_execution import (
    AnalystWallTimeTracker,
    build_analyst_execution_plan,
    get_initial_analyst_node,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree

console = Console()

from cli.display import (
    ANALYST_ORDER,
    MessageBuffer,
    _display_name,
    _display_status,
    classify_message_type,
    create_layout,
    display_complete_report,
    format_tokens,
    format_tool_args,
    update_analyst_statuses,
)
from cli.interactive_config import (
    get_analysis_date,
    validate_provider_api_key,
)

# prompt_toolkit's win32 output module is importable only on Windows (it asserts
# the platform at import time), so gate on the platform rather than catching the
# failure — that way a genuinely broken prompt_toolkit on Windows still surfaces
# instead of silently disabling the handler below. Off Windows this stays an
# empty tuple, which `except` accepts and never matches (#1138).
if sys.platform == "win32":  # pragma: no cover - platform dependent
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError

    _NO_CONSOLE_ERRORS: tuple[type[BaseException], ...] = (NoConsoleScreenBufferError,)
else:
    _NO_CONSOLE_ERRORS = ()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
    invoke_without_command=True,
    no_args_is_help=False,
)




# Create a deque to store recent messages with a maximum length


message_buffer = MessageBuffer()










def update_display(layout, spinner_text=None, stats_handler=None, start_time=None):
    # Header with welcome message
    layout["header"].update(
        Panel(
            "[bold green]TradingAgents 中文 CLI[/bold green]\n"
            "[dim]© [Tauric Research](https://github.com/TauricResearch)[/dim]",
            title="TradingAgents",
            border_style="green",
            padding=(1, 2),
            expand=True,
        )
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        box=box.SIMPLE_HEAD,  # Use simple header with horizontal lines
        title=None,  # Remove the redundant Progress title
        padding=(0, 2),  # Add horizontal padding
        expand=True,  # Make table expand to fill available space
    )
    progress_table.add_column("Team", style="cyan", justify="center", width=20)
    progress_table.add_column("智能体", style="green", justify="center", width=20)
    progress_table.add_column("状态", style="yellow", justify="center", width=20)

    # Group agents by team - filter to only include agents in agent_status
    all_teams = {
        "分析师团队": [
            "Market Analyst",
            "Social Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "研究团队": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "交易团队": ["Trader"],
        "风险管理": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "组合管理": ["Portfolio Manager"],
    }

    # Filter teams to only include agents that are in agent_status
    teams = {}
    for team, agents in all_teams.items():
        active_agents = [a for a in agents if a in message_buffer.agent_status]
        if active_agents:
            teams[team] = active_agents

    for team, agents in teams.items():
        # Add first agent with team name
        first_agent = agents[0]
        status = message_buffer.agent_status.get(first_agent, "pending")
        if status == "in_progress":
            spinner = Spinner(
                "dots", text="[blue]进行中[/blue]", style="bold cyan"
            )
            status_cell = spinner
        else:
            status_color = {
                "pending": "yellow",
                "completed": "green",
                "error": "red",
            }.get(status, "white")
            status_cell = f"[{status_color}]{_display_status(status)}[/{status_color}]"
        progress_table.add_row(team, _display_name(first_agent), status_cell)

        # Add remaining agents in team
        for agent in agents[1:]:
            status = message_buffer.agent_status.get(agent, "pending")
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text="[blue]进行中[/blue]", style="bold cyan"
                )
                status_cell = spinner
            else:
                status_color = {
                    "pending": "yellow",
                    "completed": "green",
                    "error": "red",
                }.get(status, "white")
                status_cell = f"[{status_color}]{_display_status(status)}[/{status_color}]"
            progress_table.add_row("", _display_name(agent), status_cell)

        # Add horizontal line after each team
        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="进度", border_style="cyan", padding=(1, 2))
    )

    # Messages panel showing recent messages and tool calls
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        expand=True,  # Make table expand to fill available space
        box=box.MINIMAL,  # Use minimal box style for a lighter look
        show_lines=True,  # Keep horizontal lines
        padding=(0, 1),  # Add some padding between columns
    )
    messages_table.add_column("时间", style="cyan", width=8, justify="center")
    messages_table.add_column("类型", style="green", width=10, justify="center")
    messages_table.add_column(
        "内容", style="white", no_wrap=False, ratio=1
    )  # Make content column expand

    # Combine tool calls and messages
    all_messages = []

    # Add tool calls
    for timestamp, tool_name, args in message_buffer.tool_calls:
        formatted_args = format_tool_args(args)
        all_messages.append((timestamp, "工具", f"{tool_name}: {formatted_args}"))

    # Add regular messages
    for timestamp, msg_type, content in message_buffer.messages:
        content_str = str(content) if content else ""
        if len(content_str) > 200:
            content_str = content_str[:197] + "..."
        all_messages.append((timestamp, _display_name(msg_type), content_str))

    # Sort by timestamp descending (newest first)
    all_messages.sort(key=lambda x: x[0], reverse=True)

    # Calculate how many messages we can show based on available space
    max_messages = 12

    # Get the first N messages (newest ones)
    recent_messages = all_messages[:max_messages]

    # Add messages to table (already in newest-first order)
    for timestamp, msg_type, content in recent_messages:
        # Format content with word wrapping
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    layout["messages"].update(
        Panel(
            messages_table,
            title="消息与工具",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Analysis panel showing current report
    if message_buffer.current_report:
        layout["analysis"].update(
            Panel(
                Markdown(message_buffer.current_report),
                title="当前报告",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        layout["analysis"].update(
            Panel(
                "[italic]等待分析报告生成...[/italic]",
                title="当前报告",
                border_style="green",
                padding=(1, 2),
            )
        )

    # Footer with statistics
    # Agent progress - derived from agent_status dict
    agents_completed = sum(
        1 for status in message_buffer.agent_status.values() if status == "completed"
    )
    agents_total = len(message_buffer.agent_status)

    # Report progress - based on agent completion (not just content existence)
    reports_completed = message_buffer.get_completed_reports_count()
    reports_total = len(message_buffer.report_sections)

    # Build stats parts
    stats_parts = [f"智能体: {agents_completed}/{agents_total}"]

    # LLM and tool stats from callback handler
    if stats_handler:
        stats = stats_handler.get_stats()
        stats_parts.append(f"LLM: {stats['llm_calls']}")
        stats_parts.append(f"工具: {stats['tool_calls']}")

        # Token display with graceful fallback
        if stats["tokens_in"] > 0 or stats["tokens_out"] > 0:
            tokens_str = f"Token: {format_tokens(stats['tokens_in'])}\u2191 {format_tokens(stats['tokens_out'])}\u2193"
        else:
            tokens_str = "Token: --"
        stats_parts.append(tokens_str)

    stats_parts.append(f"报告: {reports_completed}/{reports_total}")

    # Elapsed time
    if start_time:
        elapsed = time.time() - start_time
        elapsed_str = f"\u23f1 {int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        stats_parts.append(elapsed_str)

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(" | ".join(stats_parts))

    layout["footer"].update(Panel(stats_table, border_style="grey50"))


def get_user_selections(cli_config: dict | None = None):
    """Get all user selections before starting the analysis display."""
    # Display ASCII art welcome message
    with open(Path(__file__).parent / "static" / "welcome.txt", encoding="utf-8") as f:
        welcome_ascii = f.read()

    # Create welcome box content
    welcome_content = f"{welcome_ascii}\n"
    welcome_content += "[bold green]TradingAgents 多智能体交易分析框架 - 中文 CLI[/bold green]\n\n"
    welcome_content += "[bold]工作流：[/bold]\n"
    welcome_content += "I. 分析师团队 → II. 研究团队 → III. 交易员 → IV. 风险管理 → V. 组合管理\n\n"
    welcome_content += (
        "[dim]Built by [Tauric Research](https://github.com/TauricResearch)[/dim]"
    )

    # Create and center the welcome box
    welcome_box = Panel(
        welcome_content,
        border_style="green",
        padding=(1, 2),
        title="欢迎使用 TradingAgents",
        subtitle="多智能体交易分析框架",
    )
    console.print(Align.center(welcome_box))
    console.print()
    console.print()  # Add vertical space before announcements

    # Fetch and display announcements (silent on failure)
    announcements = fetch_announcements()
    display_announcements(console, announcements)

    # Create a boxed questionnaire for each step
    def create_question_box(title, prompt, default=None):
        box_content = f"[bold]{title}[/bold]\n"
        box_content += f"[dim]{prompt}[/dim]"
        if default:
            box_content += f"\n[dim]默认：{default}[/dim]"
        return Panel(box_content, border_style="blue", padding=(1, 2))

    cli_config = cli_config or {}

    def thinking_value_or_prompt(env_var, config_key, label, box_title, box_body, prompt_fn):
        """Return the env-configured reasoning/thinking value, or prompt for it.

        When ``env_var`` is set the interactive choice is skipped and the value
        the env overlay placed on DEFAULT_CONFIG is used — mirroring the
        env-precedence rule applied to the other selection steps.
        """
        if os.environ.get(env_var):
            value = DEFAULT_CONFIG[config_key]
            console.print(f"[green]✓ {label}（来自环境变量）：[/green] {value}")
            return value
        console.print(create_question_box(box_title, box_body))
        return prompt_fn()

    # Step 1: Ticker symbol
    console.print(
        create_question_box(
            "步骤 1：股票代码",
            "请输入要分析的股票代码，需要时附带交易所后缀（示例：SPY、0700.HK、002636、600519.SS、7203.T、BTC-USD）",
            "SPY",
        )
    )
    selected_ticker = (cli_config.get("run") or {}).get("ticker") or get_ticker()
    asset_type = detect_asset_type(selected_ticker)
    # Only announce when it's not the default stock path, to avoid printing
    # "stock" on every run.
    if asset_type.value != "stock":
        console.print(
            f"[green]检测到资产类型：[/green] {asset_type.value}"
        )

    # Step 2: Analysis date
    default_date = datetime.datetime.now().strftime("%Y-%m-%d")
    console.print(
        create_question_box(
            "步骤 2：分析日期",
            "请输入分析日期（YYYY-MM-DD）",
            default_date,
        )
    )
    analysis_date = (cli_config.get("run") or {}).get("analysis_date") or get_analysis_date()

    if cli_config:
        selections = build_configured_selections(
            cli_config,
            ticker=selected_ticker,
            analysis_date=analysis_date,
        )
        console.print("[green]已读取本地 JSON 配置，跳过已配置的 LLM、分析师和运行参数选择。[/green]")
        console.print(
            f"[green]分析师：[/green] {', '.join(analyst.value for analyst in selections['analysts'])}"
        )
        return selections

    # Step 3: 输出语言（设置 TRADINGAGENTS_OUTPUT_LANGUAGE 时跳过）
    if os.environ.get("TRADINGAGENTS_OUTPUT_LANGUAGE"):
        output_language = DEFAULT_CONFIG["output_language"]
        console.print(
            f"[green]✓ 输出语言（来自环境变量）：[/green] {output_language}"
        )
    else:
        console.print(
            create_question_box(
                "步骤 3：输出语言",
                "请选择分析报告和最终决策的输出语言"
            )
        )
        output_language = ask_output_language()

    # Step 4: Select analysts
    console.print(
        create_question_box(
            "步骤 4：分析师团队", "请选择参与本次分析的 LLM 智能体"
        )
    )
    selected_analysts = select_analysts(asset_type)
    console.print(
        f"[green]已选择分析师：[/green] {', '.join(analyst.value for analyst in selected_analysts)}"
    )

    # Step 5: 研究深度（两个轮次均通过环境变量设置时跳过）
    # Research depth maps to the debate + risk round counts; when both are
    # supplied through TRADINGAGENTS_MAX_DEBATE_ROUNDS / _MAX_RISK_ROUNDS we keep
    # the run non-interactive and honor the env values (#977).
    depth_from_env = bool(os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS")) and bool(
        os.environ.get("TRADINGAGENTS_MAX_RISK_ROUNDS")
    )
    if depth_from_env:
        selected_research_depth = DEFAULT_CONFIG["max_debate_rounds"]
        console.print(
            f"[green]✓ 研究深度（来自环境变量）：[/green] "
            f"{DEFAULT_CONFIG['max_debate_rounds']} debate / "
            f"{DEFAULT_CONFIG['max_risk_discuss_rounds']} risk rounds"
        )
    else:
        console.print(
            create_question_box(
                "步骤 5：研究深度", "请选择研究深度"
            )
        )
        selected_research_depth = select_research_depth()

    # Step 6: LLM Provider（设置 TRADINGAGENTS_LLM_PROVIDER 时跳过）
    # The backend URL comes from TRADINGAGENTS_LLM_BACKEND_URL when set,
    # otherwise the provider's default endpoint - the same value the menu
    # would have picked.
    provider_from_env = bool(os.environ.get("TRADINGAGENTS_LLM_PROVIDER"))
    if provider_from_env:
        selected_llm_provider = DEFAULT_CONFIG["llm_provider"].lower()
        backend_url = resolve_backend_url(
            selected_llm_provider, env_url=DEFAULT_CONFIG["backend_url"]
        )
        console.print(f"[green]✓ LLM Provider（来自环境变量）：[/green] {selected_llm_provider}")
        console.print(f"[green]✓ Backend URL：[/green] {backend_url}")
        # Still confirm/persist the API key so the run doesn't fail later.
        ensure_api_key(selected_llm_provider)
    else:
        console.print(
            create_question_box(
                "步骤 6：LLM Provider", "请选择 LLM Provider"
            )
        )
        selected_llm_provider, backend_url = select_llm_provider()

        # Providers with regional endpoints prompt for the region as a secondary
        # step so the main dropdown stays clean (mainland China and international
        # accounts cannot share API keys).
        if selected_llm_provider == "qwen":
            selected_llm_provider, backend_url = ask_qwen_region()
        elif selected_llm_provider == "minimax":
            selected_llm_provider, backend_url = ask_minimax_region()
        elif selected_llm_provider == "glm":
            selected_llm_provider, backend_url = ask_glm_region()

        # Honor an explicit env backend URL even when the provider was chosen
        # interactively, so it isn't overwritten by the menu default (#978).
        backend_url = resolve_backend_url(
            selected_llm_provider, backend_url, env_url=DEFAULT_CONFIG["backend_url"]
        )

        # For Ollama, surface the resolved endpoint (OLLAMA_BASE_URL vs default)
        # before model selection so it's obvious where we're connecting.
        if selected_llm_provider == "ollama":
            confirm_ollama_endpoint(backend_url)

        # Confirm the provider's API key is present; prompt the user to paste
        # one and persist it to .env if it's missing, so the analysis run
        # doesn't fail later at the first API call.
        ensure_api_key(selected_llm_provider)

    # Step 7: Thinking 模型（任一模型通过环境变量设置时跳过）
    if os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM") or os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM"):
        selected_shallow_thinker = DEFAULT_CONFIG["quick_think_llm"]
        selected_deep_thinker = DEFAULT_CONFIG["deep_think_llm"]
        console.print(
            f"[green]✓ Thinking 模型（来自环境变量）：[/green] "
            f"quick={selected_shallow_thinker}, deep={selected_deep_thinker}"
        )
    else:
        console.print(
            create_question_box(
                "步骤 7：Thinking 模型", "请选择用于分析的 Thinking 模型"
            )
        )
        selected_shallow_thinker = select_shallow_thinking_agent(selected_llm_provider)
        selected_deep_thinker = select_deep_thinking_agent(selected_llm_provider)

    # Step 8: Provider 专属 reasoning/thinking 配置。每个参数均可通过对应的
    # TRADINGAGENTS_* 环境变量设置；当该变量已设置（或 provider 本身来自环境变量）
    # 时跳过交互提示并使用已配置值，遵循与上方各步相同的环境变量优先规则。None =
    # 各 provider 自己的默认值。
    thinking_level = None
    reasoning_effort = None
    anthropic_effort = None
    deepseek_thinking = None
    deepseek_reasoning_effort = None

    provider_lower = selected_llm_provider.lower()
    if provider_from_env:
        thinking_level = DEFAULT_CONFIG["google_thinking_level"]
        reasoning_effort = DEFAULT_CONFIG["openai_reasoning_effort"]
        anthropic_effort = DEFAULT_CONFIG["anthropic_effort"]
        deepseek_thinking = DEFAULT_CONFIG["deepseek_thinking"]
        deepseek_reasoning_effort = DEFAULT_CONFIG["deepseek_reasoning_effort"]
    elif provider_lower == "google":
        thinking_level = thinking_value_or_prompt(
            "TRADINGAGENTS_GOOGLE_THINKING_LEVEL", "google_thinking_level",
            "Gemini thinking 模式", "步骤 8：Thinking Mode",
            "配置 Gemini thinking mode", ask_gemini_thinking_config,
        )
    elif provider_lower == "openai":
        reasoning_effort = thinking_value_or_prompt(
            "TRADINGAGENTS_OPENAI_REASONING_EFFORT", "openai_reasoning_effort",
            "OpenAI reasoning effort", "步骤 8：Reasoning Effort",
            "配置 OpenAI reasoning effort", ask_openai_reasoning_effort,
        )
    elif provider_lower == "anthropic":
        anthropic_effort = thinking_value_or_prompt(
            "TRADINGAGENTS_ANTHROPIC_EFFORT", "anthropic_effort",
            "Claude effort level", "步骤 8：Effort Level",
            "配置 Claude effort level", ask_anthropic_effort,
        )
    elif provider_lower == "deepseek":
        deepseek_thinking = thinking_value_or_prompt(
            "TRADINGAGENTS_DEEPSEEK_THINKING", "deepseek_thinking",
            "DeepSeek thinking 模式", "步骤 8：Thinking Mode",
            "配置 DeepSeek thinking mode（enabled/disabled）", ask_deepseek_thinking,
        )
        deepseek_reasoning_effort = thinking_value_or_prompt(
            "TRADINGAGENTS_DEEPSEEK_REASONING_EFFORT", "deepseek_reasoning_effort",
            "DeepSeek reasoning effort", "步骤 8：Reasoning Effort",
            "配置 DeepSeek reasoning effort（low/high/max）", ask_deepseek_effort,
        )

    return {
        "ticker": selected_ticker,
        "asset_type": asset_type.value,
        "analysis_date": analysis_date,
        "analysts": selected_analysts,
        "research_depth": selected_research_depth,
        "llm_provider": selected_llm_provider.lower(),
        "backend_url": backend_url,
        "shallow_thinker": selected_shallow_thinker,
        "deep_thinker": selected_deep_thinker,
        "google_thinking_level": thinking_level,
        "openai_reasoning_effort": reasoning_effort,
        "anthropic_effort": anthropic_effort,
        "deepseek_thinking": deepseek_thinking,
        "deepseek_reasoning_effort": deepseek_reasoning_effort,
        "output_language": output_language,
        "checkpoint_enabled": False,
        "save_report": True,
        "display_report": True,
        "data_vendors": {},
    }




def save_report_to_disk(final_state, ticker: str, save_path: Path):
    """Save the complete analysis report to disk (shared CLI/API writer)."""
    return write_report_tree(final_state, ticker, save_path)




# Ordered list of analysts for status transitions








def _build_run_config(selections: dict, checkpoint: bool | None) -> dict:
    """Assemble the run config from interactive selections, honoring env precedence.

    Round counts and checkpoint follow "explicit env/flag wins": an env-applied
    value on DEFAULT_CONFIG is preserved unless the user overrode it on the CLI.
    """
    config = copy.deepcopy(DEFAULT_CONFIG)
    # Research depth sets both round counts, but an explicit env override
    # (TRADINGAGENTS_MAX_DEBATE_ROUNDS / _MAX_RISK_ROUNDS) wins over the
    # interactive selection - leave the env-applied value in place (#977).
    if not os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS"):
        config["max_debate_rounds"] = selections["research_depth"]
    if not os.environ.get("TRADINGAGENTS_MAX_RISK_ROUNDS"):
        config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    validate_provider_api_key(config["llm_provider"])
    # Provider-specific thinking configuration
    config["google_thinking_level"] = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")
    config["anthropic_effort"] = selections.get("anthropic_effort")
    config["output_language"] = selections.get("output_language", "English")
    if selections.get("data_vendors"):
        config["data_vendors"].update(selections["data_vendors"])
    # --checkpoint/--no-checkpoint overrides only when explicitly given; omitting
    # the flag preserves TRADINGAGENTS_CHECKPOINT_ENABLED / the default (#976).
    if checkpoint is not None:
        config["checkpoint_enabled"] = checkpoint
    return config


def _publish_cli_outputs(final_state, selections: dict, cli_config: dict) -> None:
    """Apply the existing CLI save/display choices after a completed analysis."""
    should_save = bool(selections.get("save_report", True))
    if not cli_config:
        save_choice = typer.prompt("是否保存报告？", default="Y").strip().upper()
        should_save = save_choice in ("Y", "YES", "")
    if should_save:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path.cwd() / "reports" / f"{selections['ticker']}_{timestamp}"
        if cli_config:
            save_path_str = str(default_path)
        else:
            save_path_str = typer.prompt(
                "保存路径（直接回车使用默认路径）",
                default=str(default_path),
            ).strip()
        save_path = Path(save_path_str)
        try:
            report_file = save_report_to_disk(final_state, selections["ticker"], save_path)
            console.print(f"\n[green]报告已保存到：[/green] {save_path.resolve()}")
            console.print(f"  [dim]完整报告：[/dim] {report_file.name}")
        except Exception as e:
            console.print(f"[red]保存报告失败：{e}[/red]")

    should_display = bool(selections.get("display_report", True))
    if not cli_config:
        display_choice = typer.prompt("\n是否在终端展示完整报告？", default="Y").strip().upper()
        should_display = display_choice in ("Y", "YES", "")
    if should_display:
        display_complete_report(final_state)


def run_analysis(checkpoint: bool | None = None, config_path: Path | None = None):
    # First get all user selections
    try:
        cli_config = load_cli_config(config_path)
    except Exception as exc:
        raise typer.BadParameter(f"读取配置文件失败：{exc}") from exc

    selections = get_user_selections(cli_config)

    config = _build_run_config(selections, checkpoint)

    # Create stats callback handler for tracking LLM/tool calls
    stats_handler = StatsCallbackHandler()

    # Normalize analyst selection to predefined order (selection is a 'set', order is fixed)
    selected_set = {analyst.value for analyst in selections["analysts"]}
    selected_analyst_keys = [a for a in ANALYST_ORDER if a in selected_set]
    analyst_execution_plan = build_analyst_execution_plan(selected_analyst_keys)
    analyst_wall_time_tracker = AnalystWallTimeTracker(analyst_execution_plan)

    # Initialize the graph with callbacks bound to LLMs
    graph = TradingAgentsGraph(
        selected_analyst_keys,
        config=config,
        debug=False,
        callbacks=[stats_handler],
    )

    # Initialize message buffer with selected analysts
    message_buffer.init_for_analysis(selected_analyst_keys)

    # Track start time for elapsed display
    start_time = time.time()

    # Create result directory
    results_dir = Path(config["results_dir"]) / selections["ticker"] / selections["analysis_date"]
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")  # Replace newlines with spaces
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")
        return wrapper

    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")
        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                content = obj.report_sections[section_name]
                if content:
                    file_name = f"{section_name}.md"
                    text = "\n".join(str(item) for item in content) if isinstance(content, list) else content
                    with open(report_dir / file_name, "w", encoding="utf-8") as f:
                        f.write(text)
        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(message_buffer, "update_report_section")

    def add_data_progress(event):
        message_buffer.add_message("Progress", event.message)

    # Now start the display layout
    layout = create_layout()

    with progress_sink(add_data_progress), Live(layout, refresh_per_second=4):
        # Initial display
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Add initial messages
        message_buffer.add_message("System", f"已选择股票代码：{selections['ticker']}")
        if selections["asset_type"] != "stock":
            message_buffer.add_message("System", f"检测到资产类型：{selections['asset_type']}")
        message_buffer.add_message(
            "System", f"分析日期：{selections['analysis_date']}"
        )
        message_buffer.add_message(
            "System",
            f"分析师：{', '.join(analyst.value for analyst in selections['analysts'])}",
        )
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Update agent status to in_progress for the first analyst
        first_analyst = get_initial_analyst_node(analyst_execution_plan)
        message_buffer.update_agent_status(first_analyst, "in_progress")
        analyst_wall_time_tracker.mark_started(selected_analyst_keys[0])
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Create spinner text
        spinner_text = (
            f"正在分析 {selections['ticker']}，日期 {selections['analysis_date']}..."
        )
        update_display(layout, spinner_text, stats_handler=stats_handler, start_time=start_time)

        run_observer = CliRunObserver(
            message_buffer,
            wall_time_tracker=analyst_wall_time_tracker,
            classify_message=classify_message_type,
            update_analysts=update_analyst_statuses,
            refresh_display=lambda: update_display(
                layout,
                stats_handler=stats_handler,
                start_time=start_time,
            ),
        )
        request = AnalysisRequest(
            ticker=selections["ticker"],
            analysis_date=selections["analysis_date"],
            asset_type=selections["asset_type"],
            selected_analysts=tuple(selected_analyst_keys),
            max_debate_rounds=int(
                config.get("max_debate_rounds", selections["research_depth"])
            ),
            max_risk_discuss_rounds=int(
                config.get("max_risk_discuss_rounds", selections["research_depth"])
            ),
            effective_config=config,
        )
        result = graph.run_analysis(
            request,
            callbacks=[stats_handler],
            state_update_sink=run_observer,
        )
        final_state = result.final_state

        # Update all agent statuses to completed
        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "completed")

        message_buffer.add_message(
            "System", f"已完成 {selections['analysis_date']} 的分析"
        )
        message_buffer.add_message("System", analyst_wall_time_tracker.format_summary())

        # Update final report sections
        for section in message_buffer.report_sections:
            if section in final_state:
                message_buffer.update_report_section(section, final_state[section])

        update_display(layout, stats_handler=stats_handler, start_time=start_time)

    # Post-analysis prompts (outside Live context for clean interaction)
    console.print("\n[bold cyan]分析完成。[/bold cyan]\n")
    console.print(f"[dim]{analyst_wall_time_tracker.format_summary()}[/dim]")

    _publish_cli_outputs(final_state, selections, cli_config)


def _execute_analyze(
    checkpoint: bool | None,
    config: Path | None,
    clear_checkpoints: bool,
) -> None:
    """Shared dispatch for the legacy root command and explicit analyze command."""
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints

        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]已清除 {n} 个 checkpoint。[/yellow]")
    try:
        run_analysis(checkpoint=checkpoint, config_path=config)
    except _NO_CONSOLE_ERRORS:
        # A terminal with no console buffer cannot host interactive prompts.
        # Emit one actionable plain-text line instead of a prompt_toolkit
        # traceback; rich may not render in this failure mode (#1138).
        typer.echo(
            "Error: no Windows console available. The interactive CLI needs a real "
            "console buffer — run it from Windows Terminal, PowerShell, or cmd.exe "
            "rather than a piped or embedded terminal.",
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    checkpoint: bool | None = typer.Option(
        None,
        "--checkpoint/--no-checkpoint",
        help="启用/禁用 checkpoint-resume；省略时遵循环境配置。",
    ),
    config: Path | None = typer.Option(
        DEFAULT_LOCAL_CONFIG_PATH,
        "--config",
        help="本地 JSON 配置文件路径；默认尝试 tradingagents.local.json。",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="运行前删除所有 checkpoint，强制重新开始。",
    ),
):
    """Preserve the historical ``tradingagents [OPTIONS]`` invocation."""
    if ctx.invoked_subcommand is None:
        _execute_analyze(checkpoint, config, clear_checkpoints)


@app.command()
def analyze(
    checkpoint: bool | None = typer.Option(
        None,
        "--checkpoint/--no-checkpoint",
        help="启用/禁用 checkpoint-resume（每个节点后保存状态，便于崩溃后恢复）。"
        "省略时遵循 TRADINGAGENTS_CHECKPOINT_ENABLED。",
    ),
    config: Path | None = typer.Option(
        DEFAULT_LOCAL_CONFIG_PATH,
        "--config",
        help="本地 JSON 配置文件路径；默认尝试 tradingagents.local.json。",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="运行前删除所有 checkpoint，强制重新开始。",
    ),
):
    _execute_analyze(checkpoint, config, clear_checkpoints)


@app.command("web")
def web_command(
    port: int = typer.Option(
        8000,
        "--port",
        min=1,
        max=65535,
        help="本地网页端口；服务始终只绑定 127.0.0.1。",
    ),
    open_browser: bool = typer.Option(
        False,
        "--open/--no-open",
        help="服务启动时是否打开本机默认浏览器。",
    ),
):
    """Start the localhost-only TradingAgents research workbench."""
    try:
        from tradingagents.web.cli import launch_web

        launch_web(port=port, open_browser=open_browser)
    except ModuleNotFoundError as exc:
        from tradingagents.web.preflight import INSTALL_COMMAND

        console.print(
            f"Web 运行依赖缺失：{exc.name or type(exc).__name__}。",
            style="red",
        )
        console.print(f"请运行：{INSTALL_COMMAND}", markup=False, soft_wrap=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        from tradingagents.web.preflight import WebRuntimeError

        if not isinstance(exc, WebRuntimeError):
            raise
        console.print(str(exc), style="red", markup=False, soft_wrap=True)
        raise typer.Exit(code=1) from exc


@app.command("inspect-preset")
def inspect_preset_command(
    preset: Path = typer.Argument(
        ...,
        exists=True,
        readable=True,
        dir_okay=False,
        help="要校验的 YAML 分析师 preset 文件。",
    ),
):
    """Validate one v1 analyst preset without starting a graph or LLM run.

    The command deliberately renders the code-owned convergence path alongside
    the requested analyst order.  That makes the v1 boundary auditable: YAML
    may select/order existing analyst roles only; the nine downstream decision
    roles remain mandatory and cannot be disabled from a preset.
    """
    from tradingagents.analysts import MANDATORY_CONVERGENCE_NODE_IDS
    from tradingagents.presets import PresetValidationError, inspect_preset

    try:
        inspected = inspect_preset(preset)
    except PresetValidationError as exc:
        # Do not rely on Typer's rich exception renderer here.  Tooling needs a
        # stable message and a deterministic non-zero status for invalid YAML.
        typer.echo(f"Preset inspection failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    lines = [
        "Preset inspection accepted",
        f"id: {inspected.id}",
        f"label: {inspected.label}",
        "analyst_order:",
        *(f"  {index}. {analyst}" for index, analyst in enumerate(inspected.analysts, 1)),
        "mandatory_convergence_roles:",
        *(
            f"  {index}. {role}"
            for index, role in enumerate(MANDATORY_CONVERGENCE_NODE_IDS, 1)
        ),
    ]
    typer.echo("\n".join(lines))


if __name__ == "__main__":
    app()
