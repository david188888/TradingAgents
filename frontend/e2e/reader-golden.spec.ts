import { expect, test, type Page } from "@playwright/test";
import {
  alignReaderToViewport,
  mountScenario,
  openAudit,
  openCompanion,
  settleVisual,
} from "./support/reader-harness";

const runtimeProcess = (globalThis as typeof globalThis & {
  process?: { platform: string; arch: string };
}).process;
const GOLDEN_PLATFORM = runtimeProcess?.platform === "darwin" && runtimeProcess.arch === "arm64";

async function capture(page: Page, name: string): Promise<void> {
  await settleVisual(page);
  await expect(page).toHaveScreenshot(`${name}.png`);
}

test.describe("Reader golden matrix", () => {
  test.skip(!GOLDEN_PLATFORM, "Pixel baselines are generated and compared only on macOS arm64.");

  test("typed-wide-companion · 1512×982", async ({ page }) => {
    await mountScenario(page, "typed", { width: 1512, height: 982 });
    await openCompanion(page, /查看论点伴读/, "pinned");
    await alignReaderToViewport(page);
    await capture(page, "typed-wide-companion");
  });

  test("typed-wide-audit · 1440×900", async ({ page }) => {
    await mountScenario(page, "typed", { width: 1440, height: 900 });
    await openAudit(page);
    await page.locator(".audit-center-nav button", { hasText: "产物" }).click();
    await page.getByRole("button", { name: /脱敏研究报告/ }).click();
    await expect(page.locator(".audit-detail-panel:not(.audit-detail-panel--overlay)")).toBeVisible();
    await capture(page, "typed-wide-audit");
  });

  test("typed-companion-drawer · 1280×832", async ({ page }) => {
    await mountScenario(page, "typed", { width: 1280, height: 832 });
    await openCompanion(page, /查看证据伴读/, "drawer");
    await capture(page, "typed-companion-drawer");
  });

  test("typed-audit-overlay · 1200×800", async ({ page }) => {
    await mountScenario(page, "typed", { width: 1200, height: 800 });
    await openAudit(page);
    await page.locator(".audit-center-nav button", { hasText: "工具" }).click();
    await page.getByRole("button", { name: /get_fixture_market_context/ }).click();
    await expect(page.locator(".audit-detail-panel--overlay")).toBeVisible();
    await capture(page, "typed-audit-overlay");
  });

  test("typed-narrow-reader · 768×900", async ({ page }) => {
    await mountScenario(page, "typed", { width: 768, height: 900 });
    await alignReaderToViewport(page);
    await capture(page, "typed-narrow-reader");
  });

  test("partial-reader · 1440×900", async ({ page }) => {
    await mountScenario(page, "partial", { width: 1440, height: 900 });
    await alignReaderToViewport(page);
    await capture(page, "partial-reader");
  });

  test("partial-narrow-audit · 768×900", async ({ page }) => {
    await mountScenario(page, "partial", { width: 768, height: 900 });
    await openAudit(page);
    await capture(page, "partial-narrow-audit");
  });

  test("failed-reader · 1440×900", async ({ page }) => {
    await mountScenario(page, "failed", { width: 1440, height: 900 });
    await capture(page, "failed-reader");
  });

  test("failed-narrow-audit · 768×900", async ({ page }) => {
    await mountScenario(page, "failed", { width: 768, height: 900 });
    await openAudit(page);
    await capture(page, "failed-narrow-audit");
  });

  test("legacy-reader · 1440×900", async ({ page }) => {
    await mountScenario(page, "legacy", { width: 1440, height: 900 });
    await alignReaderToViewport(page);
    await capture(page, "legacy-reader");
  });

  test("legacy-narrow-audit · 768×900", async ({ page }) => {
    await mountScenario(page, "legacy", { width: 768, height: 900 });
    await openAudit(page);
    await capture(page, "legacy-narrow-audit");
  });
});
