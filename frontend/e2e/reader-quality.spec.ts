import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { PRIVATE_SENTINELS, type ReaderFixtureKind } from "./fixtures/reader-fixtures";
import { mountScenario, openAudit } from "./support/reader-harness";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"];

async function expectNoAxeViolations(page: Page, context: string): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every(
    animation => animation.playState === "finished",
  ));
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  if (result.violations.length === 0) return;
  const summary = result.violations.flatMap(violation => violation.nodes.map(
    node => `${violation.id}: ${node.target.join(" ")}`,
  )).slice(0, 30).join("\n");
  throw new Error(`${context}: ${result.violations.map(item => `${item.id}(${item.nodes.length})`).join(", ")}\n${summary}`);
}

test("initial legacy summary stays public before explicit audit selection", async ({ page }) => {
  const mounted = await mountScenario(page, "typed", { width: 1440, height: 900 });
  const initialDom = await page.locator("body").innerHTML();
  for (const sentinel of Object.values(PRIVATE_SENTINELS)) expect(initialDom).not.toContain(sentinel);
  expect(mounted.requests.companion).toBe(0);
  expect(mounted.requests.auditSummary).toBe(0);
  expect(mounted.requests.auditDetail).toBe(0);
  await openAudit(page);
  expect(mounted.requests.auditSummary).toBeGreaterThanOrEqual(1);
  expect(mounted.requests.auditDetail).toBe(0);
});

for (const kind of ["typed", "partial", "failed", "legacy"] as ReaderFixtureKind[]) {
  test(`${kind} terminal Reader has zero WCAG target violations`, async ({ page }) => {
    await mountScenario(page, kind, { width: 1440, height: 900 });
    await expectNoAxeViolations(page, `${kind} Reader`);
  });
}

test("Audit modal and inner detail overlay pass axe", async ({ page }) => {
  await mountScenario(page, "typed", { width: 1200, height: 800 });
  await openAudit(page);
  await expect(page.locator(".topbar")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".layout")).toHaveAttribute("inert", "");
  await expectNoAxeViolations(page, "Audit modal");
  await page.locator(".audit-center-nav button", { hasText: "工具" }).click();
  await page.getByRole("button", { name: /get_fixture_market_context/ }).click();
  await expect(page.getByRole("dialog", { name: "审计详情" })).toHaveAttribute("aria-modal", "true");
  await expect(page.getByTestId("audit-browser")).toHaveAttribute("aria-hidden", "true");
  await expect(page.getByTestId("audit-browser")).toHaveAttribute("inert", "");
  await expectNoAxeViolations(page, "Audit inner detail overlay");
});

test("keyboard restores focus through layered Audit Escape", async ({ page }) => {
  await mountScenario(page, "typed", { width: 1200, height: 800 });
  await page.getByRole("tab", { name: "研究过程", exact: true }).click();
  const trigger = page.getByRole("button", { name: "打开审计中心", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "关闭审计中心" })).toBeFocused();
  const tools = page.locator(".audit-center-nav button", { hasText: "工具" });
  await tools.focus();
  await page.keyboard.press("Enter");
  const tool = page.getByRole("button", { name: /get_fixture_market_context/ });
  await tool.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "返回审计列表" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(tool).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

test("reduced motion removes Audit overlay animation and transition", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mountScenario(page, "typed", { width: 1200, height: 800 });
  await openAudit(page);
  const motion = await page.locator(".audit-center").evaluate(node => {
    const style = getComputedStyle(node);
    return { animation: style.animationName, transition: style.transitionDuration };
  });
  expect(motion).toEqual({ animation: "none", transition: "0s" });
});
