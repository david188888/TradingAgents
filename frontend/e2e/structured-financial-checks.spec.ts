/** Real offline HTTP/record projection, using explicitly synthetic statements. */
import { expect, test } from "@playwright/test";

test("structured comparison passes without claiming a complete cash bridge on desktop and narrow screens", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByLabel("股票代码").fill("600519");
  await page.getByLabel("分析日期").fill("2026-09-30");
  await page.getByRole("button", { name: "开始分析", exact: true }).click();
  const reader = page.locator(".question-reader");
  await expect(reader).toBeVisible({ timeout: 20000 });
  const comparison = reader.locator('[data-follow-id="cashflow_comparison"]');
  await expect(comparison).toContainText("证据子问题已核对");
  await expect(comparison).toContainText("不代表完整现金流调节桥");
  await expect(comparison).toContainText("目前仅由一家结构化供应商");
  await expect(comparison).toContainText("尚未与官方原表互证");
  await expect(reader.locator('[data-follow-id="cash_conversion"]')).toContainText("此项资料待补");
  await comparison.getByRole("button", { name: "核对依据 →", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "依据与概念解释", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await comparison.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await expect(comparison).toContainText("不代表完整现金流调节桥");
  await page.screenshot({ path: test.info().outputPath("structured-financial-narrow.png") });
});
