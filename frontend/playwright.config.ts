import { defineConfig } from '@playwright/test'

const WEB = process.env.E2E_WEB_PORT ?? '5199'

export default defineConfig({
  testDir: 'e2e',
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: 'disabled' } },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: `http://localhost:${WEB}`, trace: 'retain-on-failure' },
  webServer: {
    command: 'bash e2e/stack.sh run',
    url: `http://localhost:${WEB}`,
    // Always a fresh stack (a reused one may serve an old build); E2E_REUSE=1 for fast local loops.
    reuseExistingServer: process.env.E2E_REUSE === '1',
    timeout: 240_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
  projects: [
    { name: 'desktop', use: { browserName: 'chromium', viewport: { width: 1366, height: 768 } } },
    { name: 'phone', use: { browserName: 'chromium', viewport: { width: 375, height: 800 } } },
  ],
})
