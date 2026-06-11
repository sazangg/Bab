import { defineConfig, devices } from "@playwright/test";

const e2eDatabasePath = `${process.cwd()}\\test-results\\e2e-bab.db`;
const backendPort = 8011;
const frontendPort = 5174;

export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  workers: 1,
  webServer: [
    {
      command:
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \"New-Item -ItemType Directory -Force -Path .\\test-results | Out-Null; Remove-Item -Force -ErrorAction SilentlyContinue .\\test-results\\e2e-bab.db; $env:PYTHONPATH='src'; $env:BAB_ENVIRONMENT='development'; $env:DATABASE_URL='sqlite+aiosqlite:///" +
        e2eDatabasePath.replace(/\\/g, "/") +
        `'; $env:BAB_SECRET_KEY='test-secret-key-with-more-than-32-chars'; $env:BAB_ENCRYPTION_KEY='mC2XCkbSXUHnJS1bAgRZ1LMvw4mDhF-GqXFf0ySFyDw='; $env:BAB_DEFAULT_ADMIN_EMAIL='owner@example.com'; $env:BAB_DEFAULT_ADMIN_PASSWORD='correct-password'; $env:BAB_PUBLIC_APP_URL='http://127.0.0.1:${frontendPort}'; Set-Location ..\\backend; .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}"`,
      url: `http://127.0.0.1:${backendPort}/api/v1/health`,
      reuseExistingServer: false,
      env: {
        E2E_DATABASE_PATH: e2eDatabasePath,
      },
    },
    {
      command: `pnpm dev --host 127.0.0.1 --port ${frontendPort}`,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      env: {
        VITE_API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
      },
    },
  ],
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    extraHTTPHeaders: {
      "x-e2e-run": "playwright",
    },
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
