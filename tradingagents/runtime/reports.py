"""Immutable partial reports and atomic canonical final report publication."""

from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from tradingagents.observability.events import ArtifactRef
from tradingagents.reporting import write_report_tree

from .run_models import utc_timestamp
from .store import RunStore, RunStoreError

REPORT_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
REVISION_PATTERN = re.compile(r"^(\d{6})-([0-9a-f]{64})\.md$")


class ReportPublicationError(RunStoreError):
    pass


@dataclass(frozen=True)
class ReportRevision:
    report_kind: str
    revision: int
    artifact: ArtifactRef


@dataclass(frozen=True)
class FinalReportPublication:
    reports_directory: Path
    complete_report: Path
    artifacts: tuple[ArtifactRef, ...]
    published_at: str


class ReportArtifactWriter:
    def __init__(self, store: RunStore):
        self.store = store

    def write_revision(
        self,
        run_id: str,
        report_kind: str,
        content: str,
    ) -> ReportRevision:
        if not REPORT_KIND_PATTERN.fullmatch(report_kind):
            raise ReportPublicationError("invalid report kind")
        if not isinstance(content, str) or not content:
            raise ReportPublicationError("report revision content is required")
        run_dir = self.store._run_dir(run_id)
        revision_dir = run_dir / "report-revisions" / report_kind
        encoded = content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()

        with self.store.lock_for(run_id):
            revision_dir.mkdir(parents=True, exist_ok=True)
            existing = [
                int(match.group(1))
                for path in revision_dir.iterdir()
                if path.is_file() and (match := REVISION_PATTERN.fullmatch(path.name))
            ]
            revision = max(existing, default=0) + 1
            filename = f"{revision:06d}-{digest}.md"
            destination = revision_dir / filename
            if destination.exists():
                raise ReportPublicationError("report revision path already exists")
            self.store._write_bytes_atomic(destination, encoded)
            self.store._fsync_directory(revision_dir)

        locator = destination.relative_to(run_dir).as_posix()
        return ReportRevision(
            report_kind=report_kind,
            revision=revision,
            artifact=ArtifactRef(
                artifact_id=f"report-revision:{digest}",
                kind="report-revision",
                media_type="text/markdown",
                content_sha256=digest,
                byte_size=len(encoded),
                locator=locator,
            ),
        )

    def write_revision_once(
        self,
        run_id: str,
        report_kind: str,
        content: str,
    ) -> ReportRevision:
        """Return the existing content-addressed revision after a promotion retry."""
        if not REPORT_KIND_PATTERN.fullmatch(report_kind):
            raise ReportPublicationError("invalid report kind")
        if not isinstance(content, str) or not content:
            raise ReportPublicationError("report revision content is required")
        run_dir = self.store._run_dir(run_id)
        revision_dir = run_dir / "report-revisions" / report_kind
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self.store.lock_for(run_id):
            if revision_dir.is_dir():
                matches = sorted(revision_dir.glob(f"*-{digest}.md"))
                if len(matches) > 1:
                    raise ReportPublicationError(
                        "duplicate content-addressed report revisions"
                    )
                if matches:
                    match = REVISION_PATTERN.fullmatch(matches[0].name)
                    if match is None or matches[0].read_text(encoding="utf-8") != content:
                        raise ReportPublicationError("report revision integrity mismatch")
                    return ReportRevision(
                        report_kind=report_kind,
                        revision=int(match.group(1)),
                        artifact=self._revision_artifact(run_dir, matches[0], digest),
                    )
            return self.write_revision(run_id, report_kind, content)

    @staticmethod
    def _revision_artifact(
        run_dir: Path,
        destination: Path,
        digest: str,
    ) -> ArtifactRef:
        content = destination.read_bytes()
        return ArtifactRef(
            artifact_id=f"report-revision:{digest}",
            kind="report-revision",
            media_type="text/markdown",
            content_sha256=digest,
            byte_size=len(content),
            locator=destination.relative_to(run_dir).as_posix(),
        )

    def publish_final(
        self,
        run_id: str,
        final_state: dict[str, Any],
        ticker: str,
    ) -> FinalReportPublication:
        if "native_research_record" in final_state:
            return self._publish_native(run_id, final_state["native_research_record"], ticker)
        if final_state.get("research_profile") == "catalyst_v1":
            return self._publish_catalyst(run_id, final_state["catalyst_case"])
        run_dir = self.store._run_dir(run_id)
        reports_dir = run_dir / "reports"
        with self.store.lock_for(run_id):
            if reports_dir.exists():
                raise ReportPublicationError("canonical reports are already published")
            temporary = run_dir / f".reports.{uuid.uuid4().hex}.tmp"
            try:
                complete = write_report_tree(final_state, ticker, temporary)
                self._verify_report_tree(temporary, complete, final_state)
                self._fsync_tree(temporary)
                os.replace(temporary, reports_dir)
                self.store._fsync_directory(run_dir)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise

        artifacts = tuple(self._final_artifacts(run_dir, reports_dir))
        return FinalReportPublication(
            reports_directory=reports_dir,
            complete_report=reports_dir / "complete_report.md",
            artifacts=artifacts,
            published_at=utc_timestamp(),
        )

    def _publish_native(self, run_id: str, value: Any, ticker: str) -> FinalReportPublication:
        from tradingagents.agents.schemas._research_record import ResearchRecordV1

        record = ResearchRecordV1.model_validate(value)
        if record.run_id != run_id or record.ticker != ticker:
            raise ReportPublicationError("native report identity mismatch")
        if record.construction != "native" or record.assessment is None:
            raise ReportPublicationError("native report requires a native assessment")
        content = build_markdown_from_native_record(record)
        run_dir = self.store._run_dir(run_id)
        reports_dir = run_dir / "reports"
        with self.store.lock_for(run_id):
            if reports_dir.exists():
                existing = reports_dir / "complete_report.md"
                if not existing.is_file() or existing.read_text(encoding="utf-8") != content:
                    raise ReportPublicationError("native report content conflict")
            else:
                temporary = run_dir / f".reports.{uuid.uuid4().hex}.tmp"
                try:
                    temporary.mkdir()
                    (temporary / "complete_report.md").write_text(content, encoding="utf-8")
                    self._fsync_tree(temporary)
                    os.replace(temporary, reports_dir)
                    self.store._fsync_directory(run_dir)
                except Exception:
                    shutil.rmtree(temporary, ignore_errors=True)
                    raise
        return FinalReportPublication(reports_directory=reports_dir,
            complete_report=reports_dir / "complete_report.md",
            artifacts=tuple(self._final_artifacts(run_dir, reports_dir)), published_at=utc_timestamp())

    def _publish_catalyst(self, run_id, value) -> FinalReportPublication:
        from tradingagents.agents.schemas import CatalystResearchCase
        from tradingagents.research.case_assembly import build_markdown_from_case
        case = CatalystResearchCase.model_validate(value)
        if case.run_id != run_id:
            raise ReportPublicationError("catalyst report identity mismatch")
        content = build_markdown_from_case(case)
        run_dir = self.store._run_dir(run_id)
        reports_dir = run_dir / "reports"
        with self.store.lock_for(run_id):
            if reports_dir.exists():
                existing = reports_dir / "complete_report.md"
                if not existing.is_file() or existing.read_text(encoding="utf-8") != content:
                    raise ReportPublicationError("catalyst report content conflict")
            else:
                temporary = run_dir / f".reports.{uuid.uuid4().hex}.tmp"
                try:
                    temporary.mkdir()
                    (temporary / "complete_report.md").write_text(content, encoding="utf-8")
                    self._fsync_tree(temporary)
                    os.replace(temporary, reports_dir)
                    self.store._fsync_directory(run_dir)
                except Exception:
                    shutil.rmtree(temporary, ignore_errors=True)
                    raise
        return FinalReportPublication(reports_directory=reports_dir,
            complete_report=reports_dir / "complete_report.md",
            artifacts=tuple(self._final_artifacts(run_dir, reports_dir)), published_at=utc_timestamp())

    @staticmethod
    def _verify_report_tree(
        temporary: Path,
        complete_report: Path,
        final_state: dict[str, Any],
    ) -> None:
        expected = {Path("complete_report.md")}
        report_paths = {
            "market_report": Path("1_analysts/market.md"),
            "sentiment_report": Path("1_analysts/sentiment.md"),
            "news_report": Path("1_analysts/news.md"),
            "fundamentals_report": Path("1_analysts/fundamentals.md"),
            "trader_investment_plan": Path("3_trading/trader.md"),
        }
        for state_key, relative in report_paths.items():
            if final_state.get(state_key):
                expected.add(relative)
        debate = final_state.get("investment_debate_state") or {}
        for state_key, filename in {
            "bull_history": "bull.md",
            "bear_history": "bear.md",
            "judge_decision": "manager.md",
        }.items():
            if debate.get(state_key):
                expected.add(Path("2_research") / filename)
        risk = final_state.get("risk_debate_state") or {}
        for state_key, filename in {
            "aggressive_history": "aggressive.md",
            "conservative_history": "conservative.md",
            "neutral_history": "neutral.md",
        }.items():
            if risk.get(state_key):
                expected.add(Path("4_risk") / filename)
        if isinstance(risk.get("risk_signals"), list):
            expected.add(Path("4_risk/public_signals.json"))
        if risk.get("judge_decision"):
            expected.add(Path("5_portfolio/decision.md"))

        if complete_report != temporary / "complete_report.md":
            raise ReportPublicationError("canonical writer returned an unexpected path")
        missing = [relative.as_posix() for relative in expected if not (temporary / relative).is_file()]
        if missing:
            raise ReportPublicationError(
                "canonical report tree is incomplete: " + ", ".join(sorted(missing))
            )

    @staticmethod
    def _fsync_tree(root: Path) -> None:
        directories = []
        for current, _dirnames, filenames in os.walk(root):
            current_path = Path(current)
            directories.append(current_path)
            for filename in filenames:
                with (current_path / filename).open("rb") as handle:
                    os.fsync(handle.fileno())
        for directory in reversed(directories):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    @staticmethod
    def _final_artifacts(run_dir: Path, reports_dir: Path):
        for path in sorted(reports_dir.rglob("*")):
            if not path.is_file():
                continue
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            yield ArtifactRef(
                artifact_id=f"report-final:{digest}",
                kind="report-final",
                media_type="text/markdown",
                content_sha256=digest,
                byte_size=len(content),
                locator=path.relative_to(run_dir).as_posix(),
            )


def _markdown_text(value: str) -> str:
    """Render saved text as inert prose, not executable HTML/Markdown links."""
    value = html.escape(value, quote=False)
    for character in ("\\", "`", "*", "_", "[", "]", "#", "|"):
        value = value.replace(character, "\\" + character)
    return value.replace("\r", " ").replace("\n", " ")


def _build_v4_native_markdown(record: Any) -> str:
    """One deterministic Reader/report source; never invokes a summary model."""
    from tradingagents.agents.schemas._research_record import ResearchRecordV1
    from tradingagents.research.coverage_labels import limitation_label

    record = ResearchRecordV1.model_validate(record.model_dump(mode="json"))
    assessment = record.assessment
    if record.construction != "native" or assessment is None:
        raise ReportPublicationError("native report requires a native assessment")
    text = _markdown_text
    claims = {item.claim_id: item for item in record.claims}
    challenges = {item.challenge_id: item for item in record.challenges}
    dimensions = {
        "operating_quality": "经营质量", "valuation": "估值依据", "market_context": "市场与价格背景",
        "catalyst_delivery": "催化兑现", "holding_thesis": "原持仓假设",
    }
    modes = {"company_research": "公司研究", "catalyst_research": "催化研究", "holding_review": "持仓复盘"}
    lines = [f"# {text(record.ticker)} · {modes[record.mode]}", "",
        f"研究截点：{record.analysis_date.isoformat()}。研究问题：{text(assessment.research_question)}", "",
        f"**{text(assessment.judgement)}**", "",
        f"证据完整性：{assessment.completeness}；研究质量：{assessment.quality}。运行完成不表示证据充分。", ""]
    if assessment.forward_window_calendar_days is not None:
        lines.extend([f"催化观察窗口：截点后 {assessment.forward_window_calendar_days} 个自然日。", ""])
    lines.extend(["## 主要风险与疑点", ""])
    if assessment.primary_challenge_id is not None:
        primary = challenges[assessment.primary_challenge_id]
        lines.extend([f"**未解决：{text(primary.statement)}**", "", f"核查方向：{text(primary.proposed_test)}", ""])
    else:
        lines.extend(["未提出额外挑战；这不表示全部风险已经排除。", ""])
    lines.extend(["## 关键依据", ""])
    for claim_id in assessment.key_claim_ids:
        claim = claims[claim_id]
        label = "事实" if claim.kind == "fact" else "条件性推断"
        lines.append(f"- [{label}] {text(claim.statement)}（{text(claim_id)}）")
    if not assessment.key_claim_ids:
        lines.append("尚无合格依据可支持关键判断。")
    lines.extend(["", "## 估值定位与参考区间", ""])
    if record.valuation is None:
        lines.append("没有合格估值输入，无法计算参考区间。")
    else:
        valuation = record.valuation
        lines.append(f"报价日期：{valuation.inputs.snapshot.as_of}；股价：{valuation.assessment.current_price} 元；总市值：{valuation.assessment.total_market_cap_yi} 亿元。")
        lines.append("历史倍数为本次抓取的回溯数据；参考区间是盈利与倍数假设下的结果，不是内在价值或未来价格预测。")
        for position in valuation.assessment.positions:
            lines.append(f"- 历史窗口 {position.window_label}：分位 {position.percentile}%，有效样本 {position.sample_size}。")
        for anchor in valuation.assessment.anchor_outputs:
            value = f"{anchor.per_share_low} 至 {anchor.per_share_high} 元/股" if anchor.per_share_low is not None else f"不可用（{anchor.reason_code}）"
            lines.append(f"- {text(anchor.method_label_zh)}：{value}；状态 {anchor.status}。")
        lines.append("输入依据：" + "、".join(text(key) for key in valuation.input_evidence_ids))
        lines.append("输入 SHA256：" + valuation.input_sha256)
    lines.extend(["", "## 脚本计算与量化背景", "",
        "下列数值来自保存的数据与计算版本，不是内在价值区间或未来价格预测。", ""])
    for metric in record.metrics:
        value = str(metric.value) + " " + text(metric.unit) if metric.availability == "available" else "不可用：" + text(metric.unavailable_reason or "原因未记录")
        lines.extend([f"- **{text(metric.label)}**：{value}。方法：{text(metric.method)}；版本：{text(metric.calculation_version)}。",
            f"  样本：{metric.sample_size if metric.sample_size is not None else '未知'}；窗口：{metric.window_start or '未知'} 至 {metric.window_end or '未知'}；输入：{', '.join(text(key) for key in metric.input_evidence_ids)}。",
            f"  输入摘要：{metric.input_sha256}。"])
        if metric.limitations:
            lines.append("  限制：" + "；".join(text(item) for item in metric.limitations))
    if not record.metrics:
        lines.append("没有通过资格检查的量化结果；不补估计值。")
    lines.extend(["", "## 下一步核查", "", text(assessment.next_check), ""])
    lines.extend(["", "## 判断维度", ""])
    for dimension in assessment.dimensions:
        lines.append(f"- **{dimensions[dimension.dimension]} · {dimension.status}**：{text(dimension.judgement)}")
        if dimension.claim_ids:
            lines.append("  依据：" + "、".join(text(key) for key in dimension.claim_ids))
        if dimension.limitations:
            lines.append("  限制：" + "；".join(text(limitation_label(item)) for item in dimension.limitations))
    lines.extend(["", "## 未解决挑战与实际核查", ""])
    for challenge in record.challenges:
        lines.append(f"- **{challenge.severity} / {challenge.risk_type}**：{text(challenge.statement)}（{text(challenge.challenge_id)}）；待核查：{text(challenge.proposed_test)}")
    if not record.challenges:
        lines.append("未提出挑战。")
    for verification in record.verifications:
        lines.append(f"- 实际核查 {text(verification.verification_id)}：{verification.status}；{text(verification.result)}")
        if verification.scope == "predicate_only":
            lines.append(f"  仅检验条件「{text(verification.condition_text or '')}」；不证明整条假设，也不自动关闭挑战。")
    if not record.verifications:
        lines.append("没有实际执行的核查记录；模型意见不属于已执行核查。")
    lines.extend(["", "## 事实、假设与未知项", ""])
    for claim in record.claims:
        lines.append(f"- [{claim.kind}] {text(claim.statement)}（{text(claim.claim_id)}）")
        if claim.evidence_ids:
            lines.append("  来源：" + "、".join(text(key) for key in claim.evidence_ids))
    for hypothesis in record.hypotheses:
        lines.append(f"- 假设 {text(hypothesis.hypothesis_id)} 的失效条件：" + "；".join(text(item) for item in hypothesis.invalidation_conditions))
        if hypothesis.limitations:
            lines.append("  限制与替代解释：" + "；".join(text(item) for item in hypothesis.limitations))
    lines.extend(["", "## 原文与来源回溯", ""])
    for source in record.evidence:
        lines.extend([f"### {text(source.source_name)} · {source.availability}", "", f"来源编号：{text(source.evidence_id)}", ""])
        lines.extend([f"披露时间：{source.published_at or '未知'}；可用于研究的时间：{source.usable_as_of or '未知'}；来源族：{text(source.source_family_id or '未知')}。", ""])
        if source.content is not None:
            content_label = {"excerpt": "保存的原文摘录", "source_fields": "保存的来源字段", "saved_summary": "保存的来源摘要（非原文）"}[source.content.kind]
            lines.extend([content_label + "：", "", "> " + text(source.content.text), "", f"内容定位：{text(source.content.locator_label)}", ""])
            if source.content.truncated:
                lines.extend(["显示内容已截断，不能视为完整原文。", ""])
        if source.public_url:
            lines.extend([f"[打开保存的来源链接]({quote(source.public_url, safe=':/?&=#%+;,@')})", ""])
        if source.limitations:
            lines.extend(["限制：" + "；".join(text(item) for item in source.limitations), ""])
    limitations = tuple(dict.fromkeys((*record.limitations, *assessment.limitations)))
    if limitations:
        lines.extend(["## 全局覆盖与专项待查", "", *("- " + text(limitation_label(item)) for item in limitations), ""])
    return "\n".join(lines).rstrip() + "\n"


def build_markdown_from_native_record(record: Any) -> str:
    """Retain byte-stable legacy reports; V4 uses the unified Reader order."""
    if record.evidence_checks is not None:
        return _build_v5_native_markdown(record)
    if record.valuation is not None or "native_valuation_policy_v1" in record.limitations:
        return _build_v4_native_markdown(record)
    return _build_legacy_native_markdown(record)


def _build_v5_native_markdown(record: Any) -> str:
    from tradingagents.agents.schemas._research_record import ResearchRecordV1
    from tradingagents.research.check_labels import (
        CHECK_LABELS,
        CHECK_STATUS,
        OUTCOME_LABELS,
        observation_value,
    )
    from tradingagents.research.coverage_labels import limitation_label

    record = ResearchRecordV1.model_validate(record.model_dump(mode="json"))
    content = _build_v4_native_markdown(record)
    text = _markdown_text
    lines = ["## 证据核查", "", "按具体问题核对保存资料；经济原因、持续性与合理价值仍需另行判断。", ""]
    for check in record.evidence_checks.checks:
        lines.extend([f"### {CHECK_LABELS[check.check_id]} · {CHECK_STATUS[check.status]}", "", text(check.question), ""])
        for observation in check.observations:
            lines.append(f"- **{text(observation.label)}**：{observation_value(observation)}。{text(observation.method)}")
        lines.extend(["", "依据："+"、".join(text(key) for key in check.evidence_ids), ""])
        for limit in (*check.limitations, *check.missing):
            lines.append("- "+text(limitation_label(limit)))
        lines.append("")
    lines.extend(["### 挑战回答范围", ""])
    for item in record.assessment.challenge_assessments:
        lines.extend([f"- **{OUTCOME_LABELS[item.outcome]} · 经济判断仍待核查**（{text(item.challenge_id)}）", "  "+text(item.rationale)])
        if item.answered_question:
            lines.append("  本次回答范围："+text(item.answered_question))
        if item.observation_date:
            lines.append("  后续观察日期："+str(item.observation_date))
        for observation in item.observations:
            lines.append("  "+text(observation.label)+"："+observation_value(observation))
    content = content.replace("## 估值定位与参考区间", "\n".join(lines)+"\n## 估值定位与参考区间", 1)
    content = content.replace("## 未解决挑战与实际核查", "## 挑战与实际核查", 1)
    content = content.replace("没有实际执行的核查记录；模型意见不属于已执行核查。", "已执行上述本地证据核查；尚未执行新增来源的独立工具验证。经济假设仍需后续验证。", 1)
    return content


def _build_legacy_native_markdown(record: Any) -> str:
    """One deterministic Reader/report source; never invokes a summary model."""
    from tradingagents.agents.schemas._research_record import ResearchRecordV1
    from tradingagents.research.coverage_labels import limitation_label

    record = ResearchRecordV1.model_validate(record.model_dump(mode="json"))
    assessment = record.assessment
    if record.construction != "native" or assessment is None:
        raise ReportPublicationError("native report requires a native assessment")
    text = _markdown_text
    claims = {item.claim_id: item for item in record.claims}
    challenges = {item.challenge_id: item for item in record.challenges}
    dimensions = {
        "operating_quality": "经营质量", "valuation": "估值依据", "market_context": "市场与价格背景",
        "catalyst_delivery": "催化兑现", "holding_thesis": "原持仓假设",
    }
    modes = {"company_research": "公司研究", "catalyst_research": "催化研究", "holding_review": "持仓复盘"}
    lines = [f"# {text(record.ticker)} · {modes[record.mode]}", "",
        f"研究截点：{record.analysis_date.isoformat()}。研究问题：{text(assessment.research_question)}", "",
        f"**{text(assessment.judgement)}**", "",
        f"证据完整性：{assessment.completeness}；研究质量：{assessment.quality}。运行完成不表示证据充分。", ""]
    if assessment.forward_window_calendar_days is not None:
        lines.extend([f"催化观察窗口：截点后 {assessment.forward_window_calendar_days} 个自然日。", ""])
    lines.extend(["## 关键依据", ""])
    for claim_id in assessment.key_claim_ids:
        claim = claims[claim_id]
        label = "事实" if claim.kind == "fact" else "条件性推断"
        lines.append(f"- [{label}] {text(claim.statement)}（{text(claim_id)}）")
    if not assessment.key_claim_ids:
        lines.append("尚无合格依据可支持关键判断。")
    lines.extend(["", "## 最大疑点与下一步", ""])
    if assessment.primary_challenge_id is not None:
        primary = challenges[assessment.primary_challenge_id]
        lines.extend([f"**未解决：{text(primary.statement)}**", "", f"核查方向：{text(primary.proposed_test)}", ""])
    else:
        lines.extend(["未提出额外挑战；这不表示全部风险已经排除。", ""])
    lines.extend([f"下一步：{text(assessment.next_check)}", "", "## 脚本计算与量化背景", "",
        "下列数值来自保存的数据与计算版本，不是内在价值区间或未来价格预测。", ""])
    for metric in record.metrics:
        value = str(metric.value) + " " + text(metric.unit) if metric.availability == "available" else "不可用：" + text(metric.unavailable_reason or "原因未记录")
        lines.extend([f"- **{text(metric.label)}**：{value}。方法：{text(metric.method)}；版本：{text(metric.calculation_version)}。",
            f"  样本：{metric.sample_size if metric.sample_size is not None else '未知'}；窗口：{metric.window_start or '未知'} 至 {metric.window_end or '未知'}；输入：{', '.join(text(key) for key in metric.input_evidence_ids)}。",
            f"  输入摘要：{metric.input_sha256}。"])
        if metric.limitations:
            lines.append("  限制：" + "；".join(text(item) for item in metric.limitations))
    if not record.metrics:
        lines.append("没有通过资格检查的量化结果；不补估计值。")
    lines.extend(["", "## 判断维度", ""])
    for dimension in assessment.dimensions:
        lines.append(f"- **{dimensions[dimension.dimension]} · {dimension.status}**：{text(dimension.judgement)}")
        if dimension.claim_ids:
            lines.append("  依据：" + "、".join(text(key) for key in dimension.claim_ids))
        if dimension.limitations:
            lines.append("  限制：" + "；".join(text(limitation_label(item)) for item in dimension.limitations))
    lines.extend(["", "## 未解决挑战与实际核查", ""])
    for challenge in record.challenges:
        lines.append(f"- **{challenge.severity} / {challenge.risk_type}**：{text(challenge.statement)}（{text(challenge.challenge_id)}）；待核查：{text(challenge.proposed_test)}")
    if not record.challenges:
        lines.append("未提出挑战。")
    for verification in record.verifications:
        lines.append(f"- 实际核查 {text(verification.verification_id)}：{verification.status}；{text(verification.result)}")
        if verification.scope == "predicate_only":
            lines.append(f"  仅检验条件「{text(verification.condition_text or '')}」；不证明整条假设，也不自动关闭挑战。")
    if not record.verifications:
        lines.append("没有实际执行的核查记录；模型意见不属于已执行核查。")
    lines.extend(["", "## 事实、假设与未知项", ""])
    for claim in record.claims:
        lines.append(f"- [{claim.kind}] {text(claim.statement)}（{text(claim.claim_id)}）")
        if claim.evidence_ids:
            lines.append("  来源：" + "、".join(text(key) for key in claim.evidence_ids))
    for hypothesis in record.hypotheses:
        lines.append(f"- 假设 {text(hypothesis.hypothesis_id)} 的失效条件：" + "；".join(text(item) for item in hypothesis.invalidation_conditions))
        if hypothesis.limitations:
            lines.append("  限制与替代解释：" + "；".join(text(item) for item in hypothesis.limitations))
    lines.extend(["", "## 原文与来源回溯", ""])
    for source in record.evidence:
        lines.extend([f"### {text(source.source_name)} · {source.availability}", "", f"来源编号：{text(source.evidence_id)}", ""])
        lines.extend([f"披露时间：{source.published_at or '未知'}；可用于研究的时间：{source.usable_as_of or '未知'}；来源族：{text(source.source_family_id or '未知')}。", ""])
        if source.content is not None:
            content_label = {"excerpt": "保存的原文摘录", "source_fields": "保存的来源字段", "saved_summary": "保存的来源摘要（非原文）"}[source.content.kind]
            lines.extend([content_label + "：", "", "> " + text(source.content.text), "", f"内容定位：{text(source.content.locator_label)}", ""])
            if source.content.truncated:
                lines.extend(["显示内容已截断，不能视为完整原文。", ""])
        if source.public_url:
            lines.extend([f"[打开保存的来源链接]({quote(source.public_url, safe=':/?&=#%+;,@')})", ""])
        if source.limitations:
            lines.extend(["限制：" + "；".join(text(item) for item in source.limitations), ""])
    limitations = tuple(dict.fromkeys((*record.limitations, *assessment.limitations)))
    if limitations:
        lines.extend(["## 全局覆盖与专项待查", "", *("- " + text(limitation_label(item)) for item in limitations), ""])
    return "\n".join(lines).rstrip() + "\n"
