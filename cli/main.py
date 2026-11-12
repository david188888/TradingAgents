"""Terminal and Web entrypoints for current V9 company research."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env", override=True)
load_dotenv(_PROJECT_ROOT / ".env.enterprise", override=False)

from cli.config import DEFAULT_LOCAL_CONFIG_PATH, build_request, load_cli_config

console = Console()
app = typer.Typer(name="TradingAgents", help="V9 多 Agent 公司证据研究", invoke_without_command=True)

_ROLE_LABELS = {
    "evidence": "证据整理", "operating_quality": "经营研究", "event_context": "事件研究",
    "market_context": "市场研究", "challenge": "质疑审阅", "synthesis": "综合判断",
    "response_operating_quality": "经营回应", "response_event_context": "事件回应",
    "response_market_context": "市场回应", "focus_response": "关注点回应",
}
_STATUS_LABELS = {"running": "进行中", "completed": "已保存", "failed": "未完成", "skipped": "跳过"}


def _progress(event):
    if event.type == "role.status_changed":
        role = (event.actor_id or "").removeprefix("native.")
        console.print(f"{_ROLE_LABELS.get(role, role)}：{_STATUS_LABELS.get(event.status, event.status)}", markup=False)
    elif event.type in {"run.started", "run.resumed"}:
        console.print(f"运行：{event.run_id}", markup=False)


def run_analysis(
    *, ticker=None, config=None, analysis_date=None, provider=None, quick_model=None, deep_model=None,
    language=None, focus=None, resume=None, run_dir=None, output=None, show=False,
):
    from cli.research import DEFAULT_RUN_ROOT, run_research
    from tradingagents.llm_clients.api_key_env import get_api_key_env
    from tradingagents.llm_clients.stage_models import stage_model_providers

    try:
        local = load_cli_config(config)
        request = None
        if not resume:
            if not ticker and not local.get("run", {}).get("ticker"):
                ticker = typer.prompt("A 股股票代码（如 002130）")
            request = build_request(local, ticker=ticker, analysis_date=analysis_date, provider=provider,
                                    quick_model=quick_model, deep_model=deep_model, language=language, focus=focus)
            import os

            for name in filter(None, map(get_api_key_env, stage_model_providers(request.effective_config))):
                if not os.getenv(name):
                    raise ValueError(f"请在 .env 或本地 JSON api_keys 中设置 {name}。")
        elif any(v is not None for v in (ticker, analysis_date, provider, quick_model, deep_model, language, focus)):
            raise ValueError("恢复使用已保存的研究配置，不能同时改动代码、日期或模型选项。")
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    root = Path(run_dir) if run_dir else DEFAULT_RUN_ROOT
    auth = None
    # Existing locally registered ChatGPT accounts are shared with the Web workbench.
    if request is None or "chatgpt" in stage_model_providers(request.effective_config):
        from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuth

        auth = ChatGPTAuth()
    try:
        from tradingagents.default_config import DEFAULT_CONFIG

        endpoint = local.get("llm", {}).get("backend_url", DEFAULT_CONFIG.get("backend_url")) if resume else None
        result = run_research(request, root, resume_run_id=resume, on_event=_progress,
                              chatgpt_auth=auth, resume_backend_url=endpoint)
    except KeyboardInterrupt:
        console.print("研究已中断；已保存进度，可用 --resume 运行编号继续。", markup=False)
        raise typer.Exit(130) from None
    except Exception as exc:
        console.print(f"研究未完成：{type(exc).__name__}。请检查保存记录中的执行状态。", style="red", markup=False)
        raise typer.Exit(1) from exc
    if output:
        target = Path(output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() != result.report.resolve():
            shutil.copyfile(result.report, target)
        console.print(f"已导出：{target.resolve()}", markup=False)
    judgement = result.record.get("synthesis")
    stance = {"favorable": "有利", "neutral": "中性", "unfavorable": "不利", None: "暂不评级"}
    console.print(f"综合判断：{stance[judgement['stance']] if judgement else '暂未形成'}", markup=False)
    console.print(f"报告：{result.report}", markup=False)
    console.print(f"运行记录：{root / result.run_id}", markup=False)
    if show or local.get("run", {}).get("display_report", False):
        console.print(Markdown(result.report.read_text(encoding="utf-8")))


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context, config: Path = typer.Option(DEFAULT_LOCAL_CONFIG_PATH, "--config", help="本地 JSON 配置。")):
    """Without a subcommand, start interactive V9 analysis."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    if ctx.invoked_subcommand is None:
        run_analysis(config=config)


@app.command()
def analyze(
    ctx: typer.Context,
    ticker: str | None = typer.Option(None, "--ticker", "-t", help="A 股代码，如 002130、600519.SS。"),
    config: Path | None = typer.Option(None, "--config", help="本地 JSON 配置。"),
    analysis_date: str | None = typer.Option(None, "--date", help="资料截至日期；默认上海当前日期。"),
    provider: str | None = typer.Option(None, "--provider", help="模型服务，默认读取环境／配置。"),
    quick_model: str | None = typer.Option(None, "--quick-model", help="专项模型。"),
    deep_model: str | None = typer.Option(None, "--deep-model", help="综合模型。"),
    language: str | None = typer.Option(None, "--language", help="Chinese 或 English。"),
    focus: str | None = typer.Option(None, "--focus", help="基础研究后回应的关注问题。"),
    resume: str | None = typer.Option(None, "--resume", help="继续保存的 V9 运行编号。"),
    run_dir: Path | None = typer.Option(None, "--run-dir", help="CLI 运行记录目录。"),
    output: Path | None = typer.Option(None, "--output", "-o", help="额外导出 Markdown 的文件路径。"),
    show: bool = typer.Option(False, "--show/--no-show", help="在终端展示完整报告。"),
):
    """V9 Insight 公司研究：独立专项 → 一轮质疑回应 → 综合判断。"""
    run_analysis(ticker=ticker, config=config or (ctx.obj or {}).get("config"), analysis_date=analysis_date, provider=provider,
                 quick_model=quick_model, deep_model=deep_model, language=language, focus=focus,
                 resume=resume, run_dir=run_dir, output=output, show=show)


@app.command("web")
def web_command(
    port: int = typer.Option(8765, "--port", min=1, max=65535),
    open_browser: bool = typer.Option(False, "--open/--no-open"),
):
    """Start the loopback-only Web research workbench."""
    from tradingagents.web.cli import launch_web

    try:
        launch_web(port=port, open_browser=open_browser)
    except (ModuleNotFoundError, RuntimeError) as exc:
        console.print(f"Web 启动失败：{exc}", style="red", markup=False)
        raise typer.Exit(1) from exc
