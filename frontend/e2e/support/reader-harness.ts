import { expect, type Page, type Route } from "@playwright/test";
import type { AuditSelectionDTO, CompanionSelectionDTO } from "../../src/api/contracts";
import {
  configFixture,
  FIXED_DATE,
  FIXED_NOW,
  scenarioFixture,
  terminalEvent,
  type ReaderFixtureKind,
  type ScenarioFixture,
} from "../fixtures/reader-fixtures";

export interface RequestCounts {
  reader: number;
  companion: number;
  auditSummary: number;
  auditDetail: number;
}

export interface MountedScenario {
  fixture: ScenarioFixture;
  requests: RequestCounts;
}

function json(route: Route, body: unknown): Promise<void> {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

function error(route: Route, status: number, code: string, message: string): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ detail: { code, message, fields: [] } }),
  });
}

export async function mountScenario(
  page: Page,
  kind: ReaderFixtureKind,
  viewport: { width: number; height: number },
): Promise<MountedScenario> {
  const fixture = scenarioFixture(kind);
  const requests: RequestCounts = {
    reader: 0,
    companion: 0,
    auditSummary: 0,
    auditDetail: 0,
  };

  await page.setViewportSize(viewport);
  await page.clock.setFixedTime(new Date(FIXED_NOW));
  await page.route("http://127.0.0.1:4173/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path === "/api/config") {
      await json(route, configFixture);
      return;
    }
    if (path === "/api/runs" && url.searchParams.get("view") === "recent") {
      await json(route, fixture.recentRuns);
      return;
    }
    if (path === `/api/runs/${fixture.runId}/view`) {
      await json(route, fixture.view);
      return;
    }
    if (path === `/api/runs/${fixture.runId}/events`) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: terminalEvent(fixture),
      });
      return;
    }
    if (path === `/api/runs/${fixture.runId}/reader/companion`) {
      requests.companion += 1;
      const kindParam = url.searchParams.get("kind");
      const id = url.searchParams.get("id");
      if (!id || !["role", "claim", "evidence", "risk"].includes(kindParam ?? "")) {
        await error(route, 404, "companion_not_found", "伴读内容不存在");
        return;
      }
      const selection = { kind: kindParam, id } as CompanionSelectionDTO;
      await json(route, fixture.companion(selection));
      return;
    }
    if (path === `/api/runs/${fixture.runId}/reader`) {
      requests.reader += 1;
      if (fixture.reader === null) {
        await error(route, 404, "reader_not_found", "失败运行没有 Reader 投影");
      } else {
        await json(route, fixture.reader);
      }
      return;
    }
    if (path === `/api/runs/${fixture.runId}/audit/detail`) {
      requests.auditDetail += 1;
      const kindParam = url.searchParams.get("kind");
      const id = url.searchParams.get("id");
      if (!id || !["run", "role", "capability", "tool", "artifact", "prompt", "config", "report"].includes(kindParam ?? "")) {
        await error(route, 404, "audit_detail_not_found", "审计详情不存在");
        return;
      }
      const selection = { kind: kindParam, id } as AuditSelectionDTO;
      await json(route, fixture.auditDetail(selection));
      return;
    }
    if (path === `/api/runs/${fixture.runId}/audit`) {
      requests.auditSummary += 1;
      await json(route, fixture.auditSummary);
      return;
    }
    if (path === `/api/runs/${fixture.runId}`) {
      await json(route, fixture.snapshot);
      return;
    }

    await error(route, 404, "fixture_route_missing", `No synthetic route for ${path}`);
  });

  await page.goto("/");
  await expect(page.locator("#ctrl-date")).toHaveValue(FIXED_DATE);
  await page.getByRole("button", { name: `打开 ${fixture.ticker} 的研究记录`, exact: true }).click();

  if (kind === "failed") {
    await expect(page.locator(".failed-run[data-ready='true']")).toBeVisible();
  } else {
    await expect(page.locator(".legacy-reader")).toHaveAttribute("data-run", fixture.runId);
    await expect(page.locator(".legacy-reader h2", { hasText: fixture.ticker })).toBeVisible();
  }
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.evaluate(() => window.scrollTo(0, 0));

  return { fixture, requests };
}

export async function openAudit(page: Page): Promise<void> {
  const readerEntry = page.locator(".reader-audit-entry");
  if (await readerEntry.count()) {
    await readerEntry.click();
  } else {
    const process = page.getByRole("tab", { name: "研究过程", exact: true });
    if (await process.count()) await process.click();
    await page.getByRole("button", { name: /^(打开|进入)审计中心$/ }).first().click();
  }
  await expect(page.getByRole("dialog", { name: "审计中心" })).toBeVisible();
  await expect(page.locator(".audit-summary-skeleton")).toHaveCount(0);
}
