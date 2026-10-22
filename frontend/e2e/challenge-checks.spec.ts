/** Synthetic offline data/models through the real run and read-only HTTP pipeline. */
import { expect, test } from "@playwright/test";

test("independent checks show their scope and missing/future tasks on desktop and narrow screens", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByLabel("股票代码").fill("600519");
  await page.getByLabel("分析日期").fill("2026-09-30");
  await page.getByRole("button", { name: "开始分析", exact: true }).click();
  const reader = page.locator(".question-reader");
  await expect(reader).toBeVisible({ timeout: 20000 });
  const primary = reader.locator("#qr-doubt");
  await expect(primary).toContainText("核查分类：当前可计算");
  await expect(primary).toContainText("任务去向：已实际执行");
  await expect(primary).toContainText("命题结果：满足");
  await expect(primary).toContainText("不证明整条经济假设，也不自动消除风险");
  await primary.getByRole("button", { name: "核对依据 →", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "依据与概念解释", exact: true });
  await expect(dialog).toContainText("任务去向：已实际执行");
  await expect(dialog).toContainText("独立核查命题");
  await page.keyboard.press("Escape");
  await reader.getByRole("button", { name: "查看全部 3 条挑战 →", exact: true }).click();
  await expect(reader.getByText("核查分类：需要补充资料", { exact: true }).first()).toBeVisible();
  await expect(reader.getByText(/模型提出的资料需求，代码未确认可用性/).first()).toBeVisible();
  const future = reader.getByText("核查分类：等待未来观察", { exact: true }).first();
  await expect(future).toBeVisible();
  await expect(reader.getByText("后续观察日期：2027-01-01", { exact: true }).first()).toBeVisible();
  await expect(reader.getByText("任务去向：未生成任务", { exact: true }).first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await future.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("challenge-checks-narrow.png") });
});
