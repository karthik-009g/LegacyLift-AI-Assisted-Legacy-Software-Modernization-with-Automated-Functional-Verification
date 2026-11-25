import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

const webDirectory = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
  testDir: path.join(webDirectory, 'tests'),
  testMatch: ['review-export.spec.ts', 'migration-settings.spec.ts'],
  globalSetup: path.join(webDirectory, 'tests', 'review-export-setup.ts'),
  workers: 1,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8011',
    browserName: 'chromium',
    channel: 'msedge',
    headless: true,
    viewport: { width: 1512, height: 1100 },
  },
});
