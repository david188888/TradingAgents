/** Real HTTP/SSE/store pipeline; synthetic model/source fixture, no paid calls. */
import { test, expect } from "@playwright/test";

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`catalyst create/read/focus ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.getByLabel("研究流程").selectOption("catalyst_v1");
    await expect(page.getByLabel("公司")).toBeVisible();
    await expect(page.getByText(/84 天/)).toBeVisible();
    await expect(page.getByLabel("研究深度")).toHaveCount(0);
    await page.getByLabel("公司").fill("600519");
    await page.getByLabel("研究问题（可选）").fill("核验订单兑现😀");
    const created = page.waitForResponse(response => response.url().endsWith("/api/runs") && response.request().method() === "POST");
    await page.getByRole("button", { name: "开始研究", exact: true }).click();
    const response = await created;
    expect(response.status()).toBe(201);
    const sent = response.request().postDataJSON();
    expect(sent.research_question).toBe("核验订单兑现😀");
    expect(sent.selected_analysts).toEqual(["market", "social", "news", "fundamentals"]);
    expect(sent.research_depth).toBe(1);
    const snapshot = await response.json();
    const brief = page.locator(".catalyst-brief");
    await expect(brief).toBeVisible({ timeout: 20000 });
    await expect(brief.locator(".catalyst-row")).toHaveCount(7);
    await expect(page.locator("[data-main-summary]")).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    for (const row of await brief.locator(".catalyst-row").all()) {
      await row.scrollIntoViewIfNeeded();
      await expect(row).toBeVisible();
    }
    const ref = brief.locator(".catalyst-ref:not(:disabled)").first();
    if (await ref.count()) {
      await ref.click();
      await expect(page.locator(".catalyst-drawer-layer")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.locator(".catalyst-drawer-layer")).toHaveCount(0);
      await expect(ref).toBeFocused();
    }
    await page.reload();
    // Selection is intentionally in-memory in the existing workbench. Reopen
    // this exact persisted run from history rather than changing that contract.
    await page.locator(`.history-item[data-run-id="${snapshot.run_id}"]`).click();
    await expect(brief).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: "分析进行中", exact: true })).toHaveCount(0);
    const read = await page.request.get(`/api/runs/${snapshot.run_id}/catalyst`);
    expect((await read.json()).research_question).toBe("核验订单兑现😀");
    await page.screenshot({ path: test.info().outputPath(`catalyst-${viewport.width}.png`), fullPage: true });
  });
}

test("catalyst form preserves classic controls across profile switch", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("研究深度").selectOption("5");
  await page.getByLabel("研究流程").selectOption("catalyst_v1");
  await page.getByLabel("研究流程").selectOption("classic");
  await expect(page.getByLabel("研究深度")).toHaveValue("5");
  await page.getByLabel("研究流程").focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("股票代码")).toBeFocused();
});

test("200 percent equivalent CSS viewport remains readable", async ({ browser }) => {
  // 1440x900 at 200% browser zoom exposes 720x450 CSS pixels. This checks
  // reflow at that space; it does not claim native browser chrome zoom proof.
  const context = await browser.newContext({ viewport: { width: 720, height: 450 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:4173/");
  await page.getByLabel("研究流程").selectOption("catalyst_v1");
  await page.getByLabel("公司").fill("600519");
  await page.getByRole("button", { name: "开始研究", exact: true }).click();
  const brief = page.locator(".catalyst-brief");
  await expect(brief).toBeVisible({ timeout: 20000 });
  for (const row of await brief.locator(".catalyst-row").all()) {
    await row.scrollIntoViewIfNeeded();
    await expect(row).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("catalyst-200-equivalent.png"), fullPage: true });
  await context.close();
});

test("cancelled catalyst has no published brief or terminal cancel action", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("研究流程").selectOption("catalyst_v1");
  await page.getByLabel("公司").fill("600519");
  const created = page.waitForResponse(response => response.url().endsWith("/api/runs") && response.request().method() === "POST");
  await page.getByRole("button", { name: "开始研究", exact: true }).click();
  const run = await (await created).json();
  await page.request.post(`/api/runs/${run.run_id}/cancel`);
  await expect(page.locator('.catalyst-progress[data-state="cancelled_or_interrupted"]')).toBeVisible();
  await expect(page.locator(".catalyst-brief")).toHaveCount(0);
  await expect(page.locator(".catalyst-progress").getByRole("button", { name: "取消", exact: true })).toHaveCount(0);
  await expect(page.locator(".catalyst-progress").getByRole("button", { name: "恢复运行", exact: true })).toHaveCount(0);
  await expect(page.locator(".catalyst-progress").getByRole("button", { name: "发起新研究" })).toBeVisible();
});
