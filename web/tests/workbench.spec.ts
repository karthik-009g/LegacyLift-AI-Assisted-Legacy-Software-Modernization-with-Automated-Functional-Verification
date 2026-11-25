import { test, expect } from '@playwright/test';

test('real workbench loads Ruby evidence and local Monaco without browser errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Understand what must survive.' })).toBeVisible();
  await expect(page.getByText('3,494', { exact: true })).toBeVisible();
  await expect(page.locator('.monaco-editor')).toBeVisible();
  await expect(page.locator('.source-list button').first()).toBeVisible();
  await page.screenshot({ path: '../artifacts/v2/workbench-desktop.png', fullPage: true });
  await page.getByRole('button', { name: /Migration 02/ }).click();
  await expect(page.getByRole('heading', { name: 'Migration setup' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate migration' })).toBeEnabled();
  await page.getByRole('button', { name: /Verification 03/ }).click();
  await expect(page.getByRole('heading', { name: 'Prove the behavior matches.' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('small viewport keeps navigation and workflow controls usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('combobox', { name: 'Workflow' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Workflow' }).selectOption('update');
  await expect(page.locator('.source-list button').first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: '../artifacts/v2/workbench-mobile.png', fullPage: true });
});
