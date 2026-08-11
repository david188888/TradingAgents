import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import {
  PRIVATE_SENTINELS,
  type ReaderFixtureKind,
} from "./fixtures/reader-fixtures";
import {
  mountScenario,
  openAudit,
  openCompanion,
} from "./support/reader-harness";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"];

async function expectNoAxeViolations(page: Page, context: string): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every(
    (animation) => animation.playState === "finished",
  ));
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  if (result.violations.length === 0) return;
  const summary = result.violations
    .flatMap((violation) => violation.nodes.map((node) => `${violation.id}: ${node.target.join(" ")}`))
    .slice(0, 30)
    .join("\n");
  throw new Error(`${context}: ${result.violations.map((item) => `${item.id}(${item.nodes.length})`).join(", ")}\n${summary}`);
}

async function expectNoPrivateSentinels(text: string): Promise<void> {
  for (const sentinel of Object.values(PRIVATE_SENTINELS)) {
    expect(text).not.toContain(sentinel);
  }
}

test("initial Reader response and DOM stay public until explicit selection", async ({ page }) => {
  const mounted = await mountScenario(page, "typed", { width: 1440, height: 900 });
  const responseText = JSON.stringify(mounted.fixture.reader);
  const initialDom = await page.locator("body").innerHTML();

  await expectNoPrivateSentinels(responseText);
  await expectNoPrivateSentinels(initialDom);
  expect(responseText).not.toMatch(/"(?:prompt|locator|content_sha256|raw|audit_refs)"/i);
  expect(responseText).not.toMatch(/[a-f0-9]{64}/i);
  expect(mounted.requests.reader).toBeGreaterThanOrEqual(1);
  expect(mounted.requests.companion).toBe(0);
  expect(mounted.requests.auditSummary).toBe(0);
  expect(mounted.requests.auditDetail).toBe(0);

  await openCompanion(page, /查看论点伴读/, "temporary");
  expect(mounted.requests.companion).toBe(1);
  expect(mounted.requests.auditSummary).toBe(0);
  expect(mounted.requests.auditDetail).toBe(0);
  await expectNoPrivateSentinels(await page.locator("body").innerHTML());
});

for (const kind of ["typed", "partial", "failed", "legacy"] as ReaderFixtureKind[]) {
  test(`${kind} terminal Reader has zero WCAG target violations`, async ({ page }) => {
    await mountScenario(page, kind, { width: 1440, height: 900 });
    await expectNoAxeViolations(page, `${kind} Reader`);
  });
}

test("Companion pinned and drawer states pass axe", async ({ page }) => {
  await mountScenario(page, "typed", { width: 1512, height: 982 });
  await openCompanion(page, /查看论点伴读/, "pinned");
  await expectNoAxeViolations(page, "Companion pinned");
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 1280, height: 832 });
  await openCompanion(page, /查看证据伴读/, "drawer");
  await expect(page.getByRole("dialog", { name: "研究伴读" })).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".topbar")).toHaveAttribute("inert", "");
  await expect(page.locator(".sidebar")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".reader-surface")).toHaveAttribute("inert", "");
  await expectNoAxeViolations(page, "Companion drawer");
});

test("Audit modal and inner detail overlay pass axe", async ({ page }) => {
  await mountScenario(page, "typed", { width: 1200, height: 800 });
  await openAudit(page);
  await expect(page.locator(".topbar")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".layout")).toHaveAttribute("inert", "");
  await expectNoAxeViolations(page, "Audit modal");
  await page.locator(".audit-center-nav button", { hasText: "工具" }).click();
  await page.getByRole("button", { name: /get_fixture_market_context/ }).click();
  const detail = page.getByRole("dialog", { name: "审计详情" });
  await expect(detail).toHaveAttribute("aria-modal", "true");
  await expect(page.getByTestId("audit-browser")).toHaveAttribute("aria-hidden", "true");
  await expect(page.getByTestId("audit-browser")).toHaveAttribute("inert", "");
  await expectNoAxeViolations(page, "Audit inner detail overlay");
});

test("keyboard flows restore focus through Companion and layered Audit Escape", async ({ page }) => {
  await mountScenario(page, "typed", { width: 1200, height: 800 });

  const companionTrigger = page.getByRole("button", { name: /查看论点伴读/ }).first();
  await companionTrigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "关闭伴读栏" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(companionTrigger).toBeFocused();

  const auditTrigger = page.locator(".reader-audit-entry");
  await auditTrigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "关闭审计中心" })).toBeFocused();
  const toolsSection = page.locator(".audit-center-nav button", { hasText: "工具" });
  await toolsSection.focus();
  await page.keyboard.press("Enter");
  const tool = page.getByRole("button", { name: /get_fixture_market_context/ });
  await tool.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "返回审计列表" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(tool).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(auditTrigger).toBeFocused();
});

test("768px is single-column and 769px is the explicit desktop boundary", async ({ page }) => {
  await mountScenario(page, "typed", { width: 768, height: 900 });
  await expect(page.locator(".layout")).toHaveCSS("display", "flex");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(768);
  expect(await page.locator(".reader-surface").evaluate((node) => {
    const element = node as HTMLElement;
    return element.scrollWidth <= element.clientWidth;
  })).toBe(true);

  await page.setViewportSize({ width: 769, height: 900 });
  await expect(page.locator(".layout")).toHaveCSS("display", "grid");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(769);
});

test("reduced motion removes Reader overlay animation and transition", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mountScenario(page, "typed", { width: 1200, height: 800 });
  await openCompanion(page, /查看论点伴读/, "drawer");
  const companionMotion = await page.locator(".companion-panel").evaluate((node) => {
    const style = getComputedStyle(node);
    return { animation: style.animationName, transition: style.transitionDuration };
  });
  expect(companionMotion).toEqual({ animation: "none", transition: "0s" });
  await page.keyboard.press("Escape");

  await openAudit(page);
  const auditMotion = await page.locator(".audit-center").evaluate((node) => {
    const style = getComputedStyle(node);
    return { animation: style.animationName, transition: style.transitionDuration };
  });
  expect(auditMotion).toEqual({ animation: "none", transition: "0s" });
});
