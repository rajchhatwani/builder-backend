import { defineConfig } from '@playwright/test'
// Written by the v2 supervisor. No backend: every API call is mocked with page.route in the specs.
export default defineConfig({
  testDir: 'e2e/v2',
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 10_000, toHaveScreenshot: { maxDiffPixelRatio: 0.005, animations: 'disabled' } },
  fullyParallel: false, workers: 1, retries: 0, reporter: [['list']],
  use: { baseURL: 'http://localhost:5299' },
  webServer: { command: 'npx vite --port 5299 --strictPort', url: 'http://localhost:5299', reuseExistingServer: true, timeout: 120_000 },
  projects: [
    ...[360, 768, 1280].flatMap((w) => (['light', 'dark'] as const).map((scheme) => ({
      name: `w${w}-${scheme}`, use: { browserName: 'chromium', viewport: { width: w, height: 900 }, colorScheme: scheme },
    }))),
  ],
})
