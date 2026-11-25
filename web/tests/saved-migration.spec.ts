import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

test('already approved generated update shows its real results and exports unchanged', async ({ page }, testInfo) => {
  const runId = '664dedffc38744058e786f61c65d0f25';
  const errors: string[] = [];
  const mutations: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  // Do not approve, generate, finalize, or change anything in the genuine saved run.
  await page.route('**/api/**', async route => {
    if (route.request().method() !== 'GET') {
      mutations.push(route.request().url());
      await route.abort();
    } else await route.continue();
  });
  const beforeResponse = await page.request.get(`/api/runs/${runId}`);
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json();
  expect(before.approval.reviewer).toBe('goku');
  expect(before.result.workflow).toBe('update');
  expect(before.result.status).toBe('passed');
  expect(before.held_out.passed_count).toBe(4);
  expect(before.held_out.scenario_count).toBe(4);

  await page.goto('/');
  await page.getByRole('button', { name: /Migration 02/ }).click();
  await page.locator('.run-list > button').filter({ hasText: runId.slice(0, 8) }).click();
  await expect(page.getByRole('combobox', { name: 'Workflow' })).toHaveValue('update');
  await expect(page.getByLabel('Evidence condition')).toHaveValue('hybrid');
  await expect(page.getByRole('heading', { name: 'Generated app.py' })).toBeVisible();
  await expect(page.locator('.monaco-editor')).toBeVisible();
  await page.getByRole('button', { name: /Verification 03/ }).click();
  await expect(page.getByText('6 of 6 scenarios match.', { exact: true })).toBeVisible();
  await expect(page.getByText('4 of 4 scenarios match.', { exact: true })).toBeVisible();
  await expect(page.getByText('Reviewed by goku')).toBeVisible();

  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download reviewed source' }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('legacylift-664dedff.zip');
  const archive = await readFile((await download.path())!);
  const exported = await page.request.get(`/api/runs/${runId}/export`);
  expect(exported.status()).toBe(200);
  expect(archive.equals(await exported.body())).toBe(true);
  const archiveSha256 = createHash('sha256').update(archive).digest('hex');
  expect(exported.headers().etag).toBe(`"${archiveSha256}"`);
  const after = await (await page.request.get(`/api/runs/${runId}`)).json();
  expect(after.approval).toEqual(before.approval);
  expect(after.source).toBe(before.source);
  expect(after.held_out).toEqual(before.held_out);
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);

  const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const evidence = path.join(repository, '.legacylift/verification');
  const capturePrefix = process.env.LEGACYLIFT_BROWSER_CAPTURE_PREFIX ?? 'approved-update-browser-20261123';
  if (!/^[A-Za-z0-9_-]+$/.test(capturePrefix)) throw new Error('Invalid browser capture prefix');
  const screenshot = path.join(evidence, `${capturePrefix}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('Verified update workbench', { path: screenshot, contentType: 'image/png' });
  const video = page.video();
  await page.close();
  const videoPath = path.join(evidence, `${capturePrefix}.webm`);
  if (video) await video.saveAs(videoPath);
  await writeFile(path.join(evidence, `${capturePrefix}.json`), JSON.stringify({
    status: 'passed', run_id: runId, guidance_matches: 6, held_out_matches: 4,
    reviewer: before.approval.reviewer, approval_modified: false, model_requests: 0,
    archive_sha256: archiveSha256, source_sha256: before.approval.source_sha256,
    browser_errors: errors, mutation_requests: mutations, synthetic_browser_fixture: false,
    video: video ? videoPath : null,
  }, null, 2));
});

test('saved create shows held-out failure and offers no export', async ({ page }) => {
  const runId = '53ea1530ef2540c7905b8ebc441ada52';
  await page.goto('/');
  await page.getByRole('button', { name: /Verification 03/ }).click();
  const run = page.locator('.run-list > button').filter({ hasText: runId.slice(0, 8) });
  await expect(run.getByText('held-out failed')).toBeVisible();
  await run.click();
  await expect(page.getByText('6 of 6 scenarios match.', { exact: true })).toBeVisible();
  await expect(page.getByText('1 of 4 scenarios match.', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download reviewed source' })).toHaveCount(0);
});
