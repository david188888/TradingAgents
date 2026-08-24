/**
 * H1 - Playwright end-to-end specs against the production boundary.
 *
 * The webServer (playwright.config.ts) starts scripts/e2e_server.py which
 * composes the real FastAPI app + SingleRunManager + RunStore with a fake
 * runner emitting a deterministic 13-role event sequence. The fake runner
 * also writes the typed public outputs (research/trader/risk/portfolio) and
 * a deterministic debate summary, so the completed-run surface exercises the
 * DecisionBrief + debate journey timeline + L2 round cards + L3 full-text
 * lanes against fixed fixtures — no live LLM or data vendor.
 *
 * 2026-07-21: the broker live-queue race was fixed. Root cause was NOT
 * broker registration timing (persist/subscribe are already mutually
 * exclusive under store.lock_for) - it was scripts/e2e_server.py creating
 * two independent broker instances: one inside SingleRunManager (worker
 * persist path) and one inside create_app (SSE subscribe path), so
 * _subscribers never saw live events and subs=0 for every persist. Fix:
 * e2e_server passes a shared broker; create_app now reuses manager.broker
 * and raises on mismatch. Real `tradingagents web` was never affected
 * (its create_app passes selected_broker into SingleRunManager).
 */
import { test, expect, type Page } from "@playwright/test";

test.describe("workbench e2e", () => {
  const TICKER = "600519.SS";

  async function startRun(page: Page): Promise<string> {
    await page.goto("/");
    await page.getByLabel("股票代码").fill(TICKER);
    await page.getByRole("button", { name: /开始分析/ }).click();
    await expect(page.getByText(TICKER).first()).toBeVisible({ timeout: 10_000 });
    return TICKER;
  }

  async function waitForRunCompleted(page: Page): Promise<void> {
    // The reader-first completed surface shows the DecisionBrief heading.
    await expect(page.locator(".decision-brief")).toBeVisible({ timeout: 30_000 });
  }

  test("completed run renders DecisionBrief and the six-stage debate journey", async ({ page }) => {
    await startRun(page);
    await waitForRunCompleted(page);

    // DecisionBrief: rating + executive summary.
    await expect(page.locator(".decision-brief").getByText("研究决策")).toBeVisible();
    await expect(page.locator(".decision-brief").getByText("Hold")).toBeVisible();

    // Six-stage timeline with measured round counts.
    const journey = page.locator(".journey");
    await expect(journey).toBeVisible();
    for (const stage of ["分析师", "证据门", "研究辩论", "交易", "风险辩论", "裁决"]) {
      await expect(journey.getByText(stage)).toBeVisible();
    }
    await expect(journey.getByText("1 轮").first()).toBeVisible();

    // Global insight strip uses committed typed outputs.
    await expect(journey.getByText("Hold")).toBeVisible();
  });

  test("expanding a stage shows L2 round cards with estimated conviction", async ({ page }) => {
    await startRun(page);
    await waitForRunCompleted(page);

    await page.locator(".journey-node").getByText("研究辩论").click();
    const stageDetail = page.locator(".stage-detail");
    await expect(stageDetail).toBeVisible();
    await expect(stageDetail.getByText("第 1 轮")).toBeVisible();
    await expect(stageDetail.getByText("多方强调品牌护城河支撑估值")).toBeVisible();
    await expect(stageDetail.getByText("80%")).toBeVisible();
    await expect(stageDetail.getByText("摘要估计").first()).toBeVisible();
  });

  test("expanding a round card shows the L3 two-lane full text", async ({ page }) => {
    await startRun(page);
    await waitForRunCompleted(page);

    await page.locator(".journey-node").getByText("研究辩论").click();
    await page.locator(".round-card-toggle").first().click();

    const detail = page.locator(".round-detail");
    await expect(detail).toBeVisible();
    await expect(detail.getByText("多方分析师")).toBeVisible();
    await expect(detail.getByText("空方分析师")).toBeVisible();
    // Full text is extracted from the same business_delta the live timeline uses.
    await expect(detail.getByText("多方：品牌护城河支撑估值")).toBeVisible({ timeout: 5_000 });
    await expect(detail.getByText("空方：估值安全边际不足")).toBeVisible({ timeout: 5_000 });
  });

  test("risk stage renders three-lane summary and the risk consensus insight", async ({ page }) => {
    await startRun(page);
    await waitForRunCompleted(page);

    await page.locator(".journey-node").getByText("风险辩论").click();
    const stageDetail = page.locator(".stage-detail");
    await expect(stageDetail.getByText("激进方认为可加仓")).toBeVisible();
    await expect(stageDetail.getByText("风险偏好")).toBeVisible();
  });

  test("opens the audit reader from the DecisionBrief", async ({ page }) => {
    await startRun(page);
    await waitForRunCompleted(page);

    await page.getByRole("button", { name: "打开审计阅读器" }).click();
    await expect(page.locator(".audit-reader")).toBeVisible();
    await expect(page.locator(".audit-reader").getByRole("heading", { name: /Trading Analysis Report/ })).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".audit-reader").getByRole("heading", { name: "I. Analyst Team Reports" })).toBeVisible();
  });

  test("history sidebar shows the completed run", async ({ page }) => {
    await startRun(page);
    await waitForRunCompleted(page);
    await expect(page.locator(".history-group-title").getByText("已完成")).toBeVisible();
    await expect(page.locator(".history-item").first()).toContainText("已完成");
  });

  test("refresh mid-run produces no missing roles and the completed surface still renders", async ({ page }) => {
    await startRun(page);
    await expect(
      page.locator(".workflow").getByText(/[1-9] \/ 13 已完成/)
    ).toBeVisible({ timeout: 10_000 });
    await page.reload();
    await page.getByText(TICKER).first().click();
    await expect(page.locator(".node")).toHaveCount(13, { timeout: 10_000 });
    await waitForRunCompleted(page);
    await expect(page.locator(".journey")).toBeVisible();
  });

  test("no configured secret appears in the DOM", async ({ page }) => {
    await startRun(page);
    await waitForRunCompleted(page);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain("fake-deepseek-e2e-key");
    expect(bodyText).not.toContain("DEEPSEEK_API_KEY");
  });

  async function clickFirstDoneNode(page: Page): Promise<void> {
    // The fake runner completes roles in sequence (~50ms each); wait for at
    // least one completed card before clicking so a turn exists.
    await expect(page.locator(".node.done").first()).toBeVisible({ timeout: 10_000 });
    await page.locator(".node.done").first().click();
  }

  test("inspector shows the fixed audit sequence and run disclosure", async ({ page }) => {
    await startRun(page);
    // The inspector is a live-audit surface backed by the reducer state;
    // click a completed role card while the run is in flight.
    await clickFirstDoneNode(page);
    await expect(page.locator(".inspector")).toBeVisible({ timeout: 5_000 });

    const inspector = page.locator(".inspector");
    const sectionHeadings = inspector.locator(".inspector-section-heading h3");
    await expect(sectionHeadings).toHaveText([
      "角色与执行事实",
      "证据、数据与工具",
      "角色输出",
    ]);
    await expect(inspector.getByText("Prompt / LLM input")).toBeVisible();

    await page.locator(".run-disclosure > summary").click();
    const disclosure = page.locator(".run-disclosure");
    await expect(disclosure.getByRole("heading", { name: "本次输入" })).toBeVisible();
    await expect(disclosure.locator(".data-table").getByText(TICKER)).toBeVisible();
    await expect(disclosure.getByRole("heading", { name: "已发布报告" })).toBeVisible();

    // Let the run finish so the next test's startRun does not hit a
    // 409 active_run_conflict (only one run may be active at a time).
    await waitForRunCompleted(page);
  });

  test("G2: inspector renders provenance and explicit no-tool state", async ({ page }) => {
    await startRun(page);
    await clickFirstDoneNode(page);
    await expect(page.locator(".inspector")).toBeVisible({ timeout: 5_000 });

    const inspector = page.locator(".inspector");
    await expect(inspector.getByRole("heading", { name: "工具调用与结果" })).toBeVisible();
    await expect(inspector.getByText("未调用工具", { exact: true })).toBeVisible();
    await expect(inspector.getByRole("heading", { name: "数据供应商来源" })).toBeVisible();

    // Let the run finish so the next test's startRun does not hit a
    // 409 active_run_conflict.
    await waitForRunCompleted(page);
  });

  test("G3: clicking a completed role card surfaces its turn in the inspector", async ({ page }) => {
    await startRun(page);
    // The fake runner paces turns; click a completed card while the run is live.
    await clickFirstDoneNode(page);
    await expect(page.locator(".role-header")).toBeVisible({ timeout: 5_000 });

    // Let the run finish so the next test's startRun does not hit a
    // 409 active_run_conflict.
    await waitForRunCompleted(page);
  });

  test("cancel a running run transitions to cancelled", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("股票代码").fill(TICKER);
    // Wait for createRun to resolve so selectRun fires and the cancel button
    // renders (fake runner completes in ~0.65s, so act fast).
    const createResponse = page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name: /开始分析/ }).click();
    await createResponse;
    const cancelBtn = page.getByRole("button", { name: "取消" });
    await expect(cancelBtn).toBeVisible({ timeout: 5_000 });
    await cancelBtn.click();
    // The cancelled run appears in the sidebar history with the cancelled badge.
    await expect(
      page.locator(".history-item").getByText("已取消"),
    ).toBeVisible({ timeout: 15_000 });
  });
});
