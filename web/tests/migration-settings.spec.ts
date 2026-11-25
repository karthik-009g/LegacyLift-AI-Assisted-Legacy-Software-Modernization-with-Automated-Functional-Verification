import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

test('generation settings reach the real job API and are omitted for other workflows', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', { name: /Migration 02/ }).click();
  await page.getByLabel('Cloud provider').selectOption('groq');
  await page.getByLabel('Generation mode').selectOption('staged');
  await page.getByLabel('Reasoning effort').selectOption('low');
  await expect(page.getByText('GET and POST are generated separately', { exact: false })).toBeVisible();
  const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  await page.screenshot({ path: path.join(repository, '.legacylift/verification/workbench-staged-settings.png'), fullPage: true });

  await page.getByRole('combobox', { name: 'Workflow', exact: true }).selectOption('create');
  await expect(page.getByLabel('Generation mode')).toHaveCount(0);
  const submit = async () => {
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/jobs') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Generate migration', exact: true }).click();
    const response = await responsePromise;
    expect(response.status(), await response.text()).toBe(202);
    const job = await response.json();
    const persisted = await (await page.request.get(`/api/jobs/${job.id}`)).json();
    // The disposable server has start_jobs=False: this queues settings but runs no model.
    expect(persisted.state).toBe('queued');
    const cancelled = await page.request.post(`/api/jobs/${job.id}/cancel`, {
      headers: { 'X-LegacyLift-Client': 'workbench' }, data: {},
    });
    expect(cancelled.status()).toBe(200);
    return persisted.parameters;
  };
  const create = await submit();
  expect(create.workflow).toBe('create');
  expect(create.staged_read).toBeUndefined();
  expect(create.groq_reasoning_effort).toBeUndefined();

  await page.getByRole('combobox', { name: 'Workflow', exact: true }).selectOption('read');
  await expect(page.getByLabel('Generation mode')).toHaveValue('staged');
  const read = await submit();
  expect(read.staged_read).toBe(true);
  expect(read.groq_reasoning_effort).toBe('low');
  expect(read.provider).toBe('groq');
  await expect(page.getByRole('button', { name: 'Generate migration', exact: true })).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel('Generation mode')).toBeVisible();
  await expect(page.getByLabel('Reasoning effort')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(repository, '.legacylift/verification/workbench-staged-settings-mobile.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('retry uses saved generation settings and exhausted runs offer no retry', async ({ page }) => {
  let remaining = 1;
  const requests: Record<string, unknown>[] = [];
  const result = () => ({
    run_id: 'browserstage', workflow: 'read', condition: 'hybrid', status: 'provider_paused',
    provider_policy: 'groq', max_repairs: 2, attempts: [], failure: { category: 'quota_exhausted' },
    call_ledger: { call_limit: 3, remaining, reserved_requests: 3 - remaining, legacy_requests_consumed: 0 },
  });
  await page.route('**/api/runs', route => route.fulfill({ json: [result()] }));
  await page.route('**/api/runs/browserstage', route => route.fulfill({ json: {
    result: result(), source: '# Synthetic settings fixture only', guidance: [], held_out: null, approval: null,
    generation_settings: { staged_read: true, groq_reasoning_effort: 'low' },
  } }));
  await page.route('**/api/jobs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    requests.push(route.request().postDataJSON());
    await route.fulfill({ status: 202, json: { id: 'syntheticretry', state: 'cancelled' } });
  });
  const select = async () => {
    await page.goto('/');
    await page.getByRole('button', { name: /Migration 02/ }).click();
    await page.locator('.run-list > button').click();
  };
  await select();
  await expect(page.getByLabel('Generation mode')).toHaveValue('staged');
  await expect(page.getByLabel('Reasoning effort')).toHaveValue('low');
  await page.getByLabel('Cloud provider').selectOption('gemini');
  await page.getByRole('button', { name: 'Retry failed provider call', exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({ run_id: 'browserstage', provider: 'groq', staged_read: true,
    groq_reasoning_effort: 'low', retry_failed_call: true });
  remaining = 0;
  await select();
  await expect(page.getByText('Request limit reached.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry failed provider call', exact: true })).toHaveCount(0);
  expect(requests).toHaveLength(1);
});
