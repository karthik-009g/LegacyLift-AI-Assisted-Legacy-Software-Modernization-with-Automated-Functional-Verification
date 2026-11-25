import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import cleanup from './review-export-teardown';

export default async function setup() {
  const url = 'http://127.0.0.1:8011/api/health';
  const existing = await fetch(url, { signal: AbortSignal.timeout(1000) }).catch(() => null);
  if (existing) throw new Error('Port 8011 is already serving; refusing to reuse it.');

  const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const fixtureHome = mkdtempSync(path.join(tmpdir(), 'legacylift-review-e2e-'));
  process.env.LEGACYLIFT_REVIEW_E2E_HOME = fixtureHome;
  const python = path.join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const server = spawn(python, [path.join(repository, 'web/tests/e2e_review_server.py'), fixtureHome], {
    cwd: repository,
    stdio: ['ignore', 'ignore', 'pipe'],
    windowsHide: true,
  });
  let diagnostics = '';
  server.stderr.on('data', chunk => { diagnostics = (diagnostics + chunk).slice(-8000); });
  server.on('error', error => { diagnostics += error.message; });
  const closed = new Promise<void>(resolve => server.once('close', () => resolve()));
  const stop = async () => {
    if (server.exitCode === null && server.signalCode === null) server.kill();
    await closed;
    // Windows keeps SQLite files locked until the owning API process has exited.
    await cleanup();
  };
  try {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (server.exitCode !== null) break;
      const response = await fetch(url, { signal: AbortSignal.timeout(1000) }).catch(() => null);
      if (response?.ok && (await response.json()).synthetic_fixture === true) return stop;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error(`Synthetic fixture server did not become ready. ${diagnostics}`);
  } catch (error) {
    await stop();
    throw error;
  }
}
