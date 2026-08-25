import { defineConfig } from "@playwright/test";

const runtimeProcess = (globalThis as typeof globalThis & {
  process?: { env: Record<string, string | undefined> };
}).process;
const isCI = Boolean(runtimeProcess?.env.CI);

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  expect: {
    timeout: 7_000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      scale: "css",
      threshold: 0.15,
      maxDiffPixelRatio: 0.002,
    },
  },
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    colorScheme: "light",
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    serviceWorkers: "block",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
  webServer: {
    // The workbench specs exercise the real FastAPI + SSE + artifact pipeline,
    // so the server under test is scripts/e2e_server.py (same-origin SPA +
    // API), not the bare Vite dev server. Point TRADINGAGENTS_E2E_PYTHON at
    // the project's interpreter when `python` is not the conda env.
    command: `${
      runtimeProcess?.env.TRADINGAGENTS_E2E_PYTHON ?? "python"
    } ../scripts/e2e_server.py`,
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !isCI,
    timeout: 30_000,
  },
});
