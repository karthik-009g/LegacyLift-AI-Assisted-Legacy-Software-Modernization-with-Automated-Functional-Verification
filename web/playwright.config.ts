import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testMatch: ['workbench.spec.ts'], workers: 1, retries: 0,
  use: { baseURL: 'http://127.0.0.1:8010', browserName: 'chromium', channel: 'msedge',
    headless: true, viewport: { width: 1512, height: 1100 } },
});
