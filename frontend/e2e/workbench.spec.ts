/** Native lifecycle over the real HTTP/SSE/store boundary, synthetic 600803 inputs. */
import { test, expect, type Page } from "@playwright/test";

const TICKER = "600803.SS";

test("keyboard switches analysis modes with an explicit selected state", async ({ page }) => {
  await page.goto("/");
  const modes = page.getByRole("group", { name: "分析模式", exact: true });
  const batch = modes.getByRole("button", { name: "批量分析", exact: true });
  await batch.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "代码或公司名称", exact: true })).toBeVisible();
  await expect(modes.getByRole("button", { name: "批量分析", exact: true })).toHaveAttribute("aria-pressed", "true");
  await modes.getByRole("button", { name: "单公司", exact: true }).focus();
  await page.keyboard.press("Space");
  await expect(page.getByLabel("股票代码")).toBeVisible();
  await expect(modes.getByRole("button", { name: "单公司", exact: true })).toHaveAttribute("aria-pressed", "true");
});

async function startRun(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("股票代码").fill(TICKER);
  await page.getByLabel("分析日期").fill("2026-09-30");
  await page.getByRole("button", { name: "开始分析", exact: true }).click();
  await expect(page.locator(".native-research-page")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".question-reader")).toBeVisible({ timeout: 20_000 });
}

test("history reopens the exact persisted completed record", async ({ page }) => {
  await startRun(page);
  const runId = await page.locator(".native-research-page").getAttribute("data-run");
  expect(runId).toBeTruthy();
  await expect(page.locator(`.history-item[data-run-id="${runId}"]`)).toContainText("已完成");
  await page.reload();
  await page.locator(`.history-item[data-run-id="${runId}"]`)
    .getByRole("button", { name: `打开 ${TICKER} 的研究记录`, exact: true }).click();
  await expect(page.locator(".native-research-page")).toHaveAttribute("data-run", runId!);
});

test("configured secrets remain absent from the completed DOM", async ({ page }) => {
  await startRun(page);
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toContain("fake-deepseek-e2e-key");
  expect(bodyText).not.toContain("synthetic-fixture-key");
  expect(bodyText).not.toContain("DEEPSEEK_API_KEY");
});

test("cancel a running run transitions to cancelled", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("股票代码").fill(TICKER);
  await page.getByLabel("分析日期").fill("2026-09-30");
  const created = page.waitForResponse(
    response => response.url().endsWith("/api/runs") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "开始分析", exact: true }).click();
  const snapshot = await (await created).json();
  const cancel = page.getByRole("button", { name: "取消研究", exact: true });
  await expect(cancel).toBeVisible();
  await cancel.click();
  await expect(page.locator(`.history-item[data-run-id="${snapshot.run_id}"]`)).toContainText("已取消");
});

for (const viewport of [{ width: 1512, height: 900 }, { width: 1280, height: 650 }]) {
  test(`stage review reveals details and returns focus at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.getByLabel("股票代码").fill(TICKER);
    await page.getByLabel("分析日期").fill("2026-09-30");
    await page.getByRole("button", { name: "开始分析", exact: true }).click();
    // Cancel this synthetic run to keep the progress surface stable during review.
    // It uses the same stage links as a running analysis, without paid calls.
    await page.getByRole("button", { name: "取消研究", exact: true }).click();
    await expect(page.getByRole("heading", { name: "研究已取消", exact: true })).toBeVisible();
    const stages = page.locator(".native-progress .qr-process-step");
    const detail = page.getByRole("region", { name: "所选环节详情", exact: true });
    for (let i = 0; i < await stages.count(); i++) {
      const stage = stages.nth(i);
      const label = (await stage.getByRole("heading").innerText()).split(" · ")[0];
      const entry = stage.getByRole("button", { name: "查看本环节与保存产物 →", exact: true });
      await entry.focus();
      await page.keyboard.press("Enter");
      await expect(detail).toBeFocused();
      await expect(detail.getByRole("heading", { name: label, exact: true })).toBeInViewport();
      await expect(entry).toHaveAttribute("aria-expanded", "true");
      await expect(detail.getByRole("status")).not.toContainText("产物暂时无法读取");
      // A second click on the same role must reveal the existing review again.
      await entry.click();
      await expect(detail).toBeFocused();
      await expect(detail.getByRole("heading", { name: label, exact: true })).toBeInViewport();
      await detail.getByRole("button", { name: "收起角色回顾", exact: true }).click();
      await expect(entry).toBeFocused();
      await expect(entry).toBeInViewport();
      await expect(detail).toHaveCount(0);
    }
  });
}
