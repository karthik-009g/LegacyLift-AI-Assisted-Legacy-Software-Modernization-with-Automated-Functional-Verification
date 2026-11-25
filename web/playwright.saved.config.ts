import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

const webDirectory = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(webDirectory, '..');
const python = path.join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

export default defineConfig({
  testDir: path.join(webDirectory, 'tests'),
  testMatch: ['saved-migration.spec.ts'],
  workers: 1,
  retries: 0,
  webServer: {
    command: `"${python}" "${path.join(webDirectory, 'tests/e2e_saved_server.py')}"`,
    url: 'http://127.0.0.1:8012/api/health',
    reuseExistingServer: false,
  },
  use: {
    baseURL: 'http://127.0.0.1:8012',
    browserName: 'chromium',
    channel: 'msedge',
    headless: true,
    viewport: { width: 1512, height: 1100 },
    video: 'on',
  },
});
