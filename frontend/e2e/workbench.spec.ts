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
  await expect(page.locator(".research-record")).toBeVisible({ timeout: 20_000 });
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
  const cancel = page.getByRole("button", { name: "取消", exact: true });
  await expect(cancel).toBeVisible();
  await cancel.click();
  await expect(page.locator(`.history-item[data-run-id="${snapshot.run_id}"]`)).toContainText("已取消");
});
