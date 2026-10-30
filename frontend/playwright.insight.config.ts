import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

const env = (globalThis as typeof globalThis & {process?: {env: Record<string, string | undefined>}}).process?.env;
export default defineConfig({
  ...base,
  testMatch: "insight-research.spec.ts",
  use: {...base.use, baseURL: "http://127.0.0.1:4183"},
  webServer: {
    command: `TRADINGAGENTS_E2E_INSIGHT=1 TRADINGAGENTS_E2E_PORT=4183 ${env?.TRADINGAGENTS_E2E_PYTHON ?? "python"} ../scripts/catalyst_e2e_server.py`,
    url: "http://127.0.0.1:4183", reuseExistingServer: false, timeout: 30000,
  },
});
