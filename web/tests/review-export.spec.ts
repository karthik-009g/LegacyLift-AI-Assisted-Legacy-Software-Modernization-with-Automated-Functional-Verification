import { readFile, stat } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test('synthetic browser fixture completes source review and checksum-bound ZIP export', async ({ page }) => {
  const runId = `e2e${'0'.repeat(29)}`;
  const browserErrors: string[] = [];
  page.on('pageerror', error => browserErrors.push(error.message));

  await page.goto('/');
  await expect(page.getByRole('status').getByText('Synthetic test fixture')).toBeVisible();
  await expect(page.getByText(/not a Redmine migration result or real verification/)).toBeVisible();

  await page.getByRole('button', { name: /Migration 02/ }).click();
  await expect(page.getByRole('heading', { name: 'Migration setup' })).toBeVisible();
  await expect(page.locator('.run-list > button')).toHaveCount(1);
  await page.locator('.run-list > button').click();
  await expect(page.getByRole('heading', { name: 'Generated app.py' })).toBeVisible();
  await expect(page.locator('.monaco-editor')).toBeVisible();
  await expect(page.getByText('synthetic fixture · test only')).toBeVisible();

  await page.getByRole('button', { name: /Verification 03/ }).click();
  await expect(page.getByRole('heading', { name: 'Behavior comparison' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Guidance verification' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Final held-out verification' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Review & export' })).toBeVisible();
  await expect(page.getByText('1 of 1 scenarios match.', { exact: true })).toHaveCount(2);

  await page.getByLabel('Reviewer').fill('Browser E2E Reviewer');
  await page.getByLabel('Review notes').fill('Reviewed synthetic source and test-only limitations.');
  await page.getByLabel('I reviewed the generated source and its stated limitations.').check();

  const approvalResponse = page.waitForResponse(response =>
    response.url().endsWith(`/api/runs/${runId}/approve`)
      && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Approve this source' }).click();
  const approved = await approvalResponse;
  expect(approved.status(), await approved.text()).toBe(200);
  await expect(page.getByText('Reviewed by Browser E2E Reviewer')).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download reviewed source' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('legacylift-e2e00000.zip');
  const archivePath = await download.path();
  expect(archivePath).not.toBeNull();
  const archive = await readFile(archivePath!);
  expect(archive.subarray(0, 4).toString('hex')).toBe('504b0304');
  expect((await stat(archivePath!)).size).toBeGreaterThan(256);

  const detail = await page.request.get(`/api/runs/${runId}`);
  expect(detail.status()).toBe(200);
  const payload = await detail.json();
  expect(payload.approval.reviewer).toBe('Browser E2E Reviewer');
  expect(payload.approval.source_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(payload.approval.verification_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(browserErrors).toEqual([]);
});
