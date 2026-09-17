import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests", testMatch: "mobile.spec.ts", fullyParallel: false, workers: 1,
  use: { baseURL: "http://127.0.0.1:3102", trace: "retain-on-failure", ...devices["Pixel 7"] },
  webServer: { command: "npm run start -- --hostname 127.0.0.1 --port 3102", url: "http://127.0.0.1:3102", reuseExistingServer: false, timeout: 60000 },
});
