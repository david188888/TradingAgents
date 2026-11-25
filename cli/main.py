"""Terminal and Web entrypoints for current V9 company research."""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
from contextlib import redirect_stdout
from enum import Enum
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env", override=True)
load_dotenv(_PROJECT_ROOT / ".env.enterprise", override=False)

from cli.config import DEFAULT_LOCAL_CONFIG_PATH, build_request, load_cli_config
from cli.headless import HeadlessOutput

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


class CitationStyle(str, Enum):
    raw = "raw"
    numbered = "numbered"


def _plan_summary(request):
    from tradingagents.execution.config_identity import native_effective_config
    from tradingagents.llm_clients.stage_models import stage_model_overrides
    from tradingagents.research.native_versions import INSIGHT_WORKFLOW_VERSION

    config = native_effective_config(request.effective_config, INSIGHT_WORKFLOW_VERSION)
    try:
        timeout = float(config.get("evidence_timeout_seconds", 300))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("研究时限必须是正数。") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("研究时限必须是正数。")
    return {
        "ticker": request.ticker, "analysis_date": request.analysis_date,
        "workflow_version": INSIGHT_WORKFLOW_VERSION, "language": config["output_language"],
        "provider": config["llm_provider"], "quick_model": config["quick_think_llm"],
        "deep_model": config["deep_think_llm"],
        "stage_models": {stage: {"provider": value["provider"], "model": value["model"]}
                         for stage, value in sorted(stage_model_overrides(config).items())},
        "search_enabled": config["evidence_search_enabled"],
        "decision_verification_enabled": config.get("jev_verification_enabled", False),
        "timeout_seconds": timeout, "has_focus": request.research_question is not None,
    }


def run_analysis(
    *, ticker=None, config=None, analysis_date=None, provider=None, quick_model=None, deep_model=None,
    language=None, focus=None, resume=None, run_dir=None, output=None, show=False,
    stream=None, plan=False, citation_style=CitationStyle.raw,
):
    from cli.research import DEFAULT_RUN_ROOT, run_research
    from tradingagents.llm_clients.api_key_env import missing_provider_env
    from tradingagents.llm_clients.stage_models import stage_model_providers

    root = Path(run_dir).expanduser() if run_dir else DEFAULT_RUN_ROOT
    try:
        if plan and (resume or output or show):
            raise ValueError("--plan 只预检新研究，不能与 --resume、--output 或 --show 同用。")
        if stream and show:
            raise ValueError("--json 不支持 --show；可使用 --output 导出报告。")
        if citation_style == CitationStyle.numbered and not (output or show):
            raise ValueError("--citation-style numbered 需要 --output 或 --show。")
        target = Path(output).expanduser().resolve() if output else None
        if target and (stream or citation_style == CitationStyle.numbered) and target.is_relative_to(root.resolve()):
            raise ValueError("--output 必须位于运行记录目录之外。")
        local = load_cli_config(config)
        request = None
        if not resume:
            run_options = local.get("run", {})
            if not ticker and isinstance(run_options, dict) and not run_options.get("ticker"):
                if stream or plan:
                    raise ValueError("请提供 --ticker，或在配置中设置 run.ticker。")
                ticker = typer.prompt("A 股股票代码（如 002130）")
            request = build_request(local, ticker=ticker, analysis_date=analysis_date, provider=provider,
                                    quick_model=quick_model, deep_model=deep_model, language=language, focus=focus)
            if plan:
                summary = _plan_summary(request)
                if stream:
                    stream.result("planned", plan=summary)
                else:
                    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
                return
            for selected_provider in stage_model_providers(request.effective_config):
                if selected_provider == "chatgpt":
                    continue
                for name in missing_provider_env(selected_provider, os.environ):
                    raise ValueError(f"请在 .env 或本地 JSON api_keys 中设置 {name}。")
        elif any(v is not None for v in (ticker, analysis_date, provider, quick_model, deep_model, language, focus)):
            raise ValueError("恢复使用已保存的研究配置，不能同时改动代码、日期或模型选项。")
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if stream:
        stream.run_id = resume
        stream.emit("command.started", run_id=resume)
        if stream.failed:
            return  # Do not make a provider call when the output channel is already closed.
    auth = None
    # Existing locally registered ChatGPT accounts are shared with the Web workbench.
    if request is None or "chatgpt" in stage_model_providers(request.effective_config):
        from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuth, validate_account_models
        from tradingagents.llm_clients.chatgpt_errors import ChatGPTError

        auth = ChatGPTAuth()
        if request is not None:
            config = request.effective_config
            selected = [entry["model"] for entry in config.get("stage_models", {}).values()
                        if entry["provider"] == "chatgpt"]
            if config["llm_provider"] == "chatgpt":
                selected.extend((config["quick_think_llm"], config["deep_think_llm"]))
            try:
                validate_account_models(auth, config["chatgpt_account_ref"], selected)
            except ChatGPTError as exc:
                console.print(str(exc), style="red", markup=False)
                raise typer.Exit(1) from exc
    from tradingagents.execution.insight_model import DecisionVerificationFailed

    try:
        from tradingagents.default_config import DEFAULT_CONFIG

        endpoint = local.get("llm", {}).get("backend_url", DEFAULT_CONFIG.get("backend_url")) if resume else None
        result = run_research(request, root, resume_run_id=resume, on_event=stream.event if stream else _progress,
                              chatgpt_auth=auth, resume_backend_url=endpoint)
    except KeyboardInterrupt:
        console.print("研究已中断；已保存进度，可用 --resume 运行编号继续。", markup=False)
        raise typer.Exit(130) from None
    except DecisionVerificationFailed as exc:
        console.print(f"研究未完成：决策核验未通过执行。{exc}", style="red", markup=False)
        raise typer.Exit(1) from exc
    except Exception as exc:
        console.print(f"研究未完成：{type(exc).__name__}。请检查保存记录中的执行状态。", style="red", markup=False)
        raise typer.Exit(1) from exc
    if stream:
        stream.run_id = result.run_id
    try:
        numbered = None
        if citation_style == CitationStyle.numbered:
            from tradingagents.agents.schemas._insight import InsightReport
            from tradingagents.research.insight_report import insight_markdown

            numbered = insight_markdown(InsightReport.model_validate(result.record), numbered=True)
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            if numbered is not None:
                target.write_text(numbered, encoding="utf-8")
            elif target != result.report.resolve():
                shutil.copyfile(result.report, target)
            if not stream:
                console.print(f"已导出：{target}", markup=False)
        judgement = result.record.get("synthesis")
        if stream:
            stream.result("completed", published=True, report_path=str(result.report.resolve()),
                          export_path=str(target) if target else None,
                          stance=judgement["stance"] if judgement else None)
            return
        stance = {"favorable": "有利", "neutral": "中性", "unfavorable": "不利", None: "暂不评级"}
        console.print(f"综合判断：{stance[judgement['stance']] if judgement else '暂未形成'}", markup=False)
        console.print(f"报告：{result.report}", markup=False)
        console.print(f"运行记录：{root / result.run_id}", markup=False)
        if show or local.get("run", {}).get("display_report", False):
            console.print(Markdown(numbered if numbered is not None else result.report.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        console.print(f"研究已保存，但无法导出或显示报告：{type(exc).__name__}。", style="red", markup=False)
        if stream:
            stream.result("failed", reason="report_output", published=True, report_path=str(result.report.resolve()))
        raise typer.Exit(1) from exc


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
    json_output: bool = typer.Option(False, "--json", help="无交互；逐行输出 JSON 事件与最终结果。"),
    plan: bool = typer.Option(False, "--plan", help="仅预检并显示新研究的配置，不执行研究。"),
    citation_style: CitationStyle = typer.Option(CitationStyle.raw, "--citation-style", help="仅影响额外导出或显示的来源引用。"),
):
    """V9 Insight 公司研究：独立专项 → 按需核验与质疑 → 综合判断。"""
    options = {"ticker": ticker, "config": config or (ctx.obj or {}).get("config"), "analysis_date": analysis_date,
               "provider": provider, "quick_model": quick_model, "deep_model": deep_model, "language": language,
               "focus": focus, "resume": resume, "run_dir": run_dir, "output": output, "show": show,
               "plan": plan, "citation_style": citation_style}
    if not json_output:
        run_analysis(**options)
        return
    stream = HeadlessOutput(sys.stdout)
    with redirect_stdout(sys.stderr):
        try:
            run_analysis(**options, stream=stream)
        except typer.BadParameter:
            stream.result("invalid_input", reason="bad_parameter")
            raise
        except (KeyboardInterrupt, typer.Exit) as exc:
            code = exc.exit_code if isinstance(exc, typer.Exit) else 130
            stream.result("interrupted" if code == 130 else "failed")
            raise typer.Exit(code) from exc
        except Exception as exc:
            console.print(f"研究未完成：{type(exc).__name__}。", style="red", markup=False)
            stream.result("failed")
            raise typer.Exit(1) from exc
        finally:
            if stream.failed:
                typer.echo("JSONL 输出无法写入；请检查运行记录。", err=True)
                raise typer.Exit(1)


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
