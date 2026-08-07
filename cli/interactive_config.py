"""Interactive configuration and input validation for the TradingAgents CLI."""

from __future__ import annotations

import datetime
import os
from pathlib import Path

import typer

from cli.display import console
from tradingagents.llm_clients.api_key_env import get_api_key_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def validate_provider_api_key(provider: str) -> None:
    """Fail early when the selected hosted LLM provider has no loaded API key."""
    provider = provider.lower()
    env_name = get_api_key_env(provider)
    if not env_name:
        return
    if os.getenv(env_name):
        return
    raise typer.BadParameter(
        f"未加载 provider '{provider}' 的 API key。请在 {PROJECT_ROOT / '.env'} 或本地 JSON 配置中设置 {env_name}。"
    )


def get_analysis_date():
    """Get the analysis date from user input."""
    while True:
        date_str = typer.prompt(
            "", default=datetime.datetime.now().strftime("%Y-%m-%d")
        )
        try:
            # Validate date format and ensure it's not in the future
            analysis_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if analysis_date.date() > datetime.datetime.now().date():
                console.print("[red]错误：分析日期不能晚于今天。[/red]")
                continue
            return date_str
        except ValueError:
            console.print(
                "[red]错误：日期格式无效，请使用 YYYY-MM-DD。[/red]"
            )

