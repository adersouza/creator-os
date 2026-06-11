import { defineConfig } from "@playwright/test";
import dotenv from "dotenv";
import { fileURLToPath } from "url";
import { dirname, resolve } from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

dotenv.config({ path: resolve(__dirname, ".env.test") });

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI
    ? [["html", { outputFolder: "playwright-report", open: "never" }], ["list"]]
    : [["list"]],

  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: "chromium",
      use: {
        browserName: "chromium",
        storageState: "e2e/.auth/user.json",
      },
      testMatch: /dashboard\.spec\.ts|publish-threads\.spec\.ts|publish-instagram\.spec\.ts|post-lifecycle\.spec\.ts|operator-workflows\.spec\.ts/,
      dependencies: ["setup"],
    },
    {
      name: "mobile-chrome",
      use: {
        browserName: "chromium",
        viewport: { width: 375, height: 812 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
      },
      testMatch: /mobile\.spec\.ts/,
    },
    {
      name: "critical",
      use: {
        browserName: "chromium",
        storageState: "e2e/.auth/user.json",
      },
      testMatch: /composer-critical\.spec\.ts/,
      dependencies: ["setup"],
    },
    {
      name: "scale",
      use: {
        browserName: "chromium",
      },
      testMatch: /scale-200\.spec\.ts/,
    },
    {
      name: "smoke",
      use: {
        browserName: "chromium",
        baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
      },
      testMatch: /smoke\.spec\.ts/,
    },
    {
      name: "storybook",
      use: {
        browserName: "chromium",
        baseURL: "http://localhost:6006",
      },
      testMatch: /visual-regression\.spec\.ts/,
    },
  ],

  // Server lifecycle is owned by the caller — the CI workflow boots
  // `vite preview` and waits for it before invoking Playwright; for local
  // dev, run `npm run dev` in another tab. Removing webServer here avoids
  // the failure mode where Playwright tries to spin up its own server even
  // with reuseExistingServer:true and times out at 60s.
});
