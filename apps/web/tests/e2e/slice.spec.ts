import { expect, test } from '@playwright/test';

// No mocks: every request goes through the app's /api rewrite to the real backend (VERA_API_ORIGIN).
test('queue → CHG-1042 → open → hold → resume → evaluate policy → cardholder view', async ({ page, request }) => {
  expect((await request.post('/api/demo/reset')).ok()).toBe(true);
  await page.goto('/cases');
  await page.getByRole('link', { name: 'CHG-1042 · Northstar Equipment' }).click();
  await expect(page).toHaveURL(/\/cases\/CHG-1042/);
  await expect(page.getByTestId('case-state')).toHaveText('New report');

  const acts = page.getByRole('group', { name: 'Case actions' });
  const primary = acts.locator('[data-primary="true"]');
  await expect(primary).toHaveText('Open case');
  await primary.click();
  await expect(page.getByTestId('case-state')).not.toHaveText('New report');
  const afterOpen = await page.getByTestId('case-state').textContent();

  await acts.getByRole('button', { name: 'Hold for more information' }).click();
  await page.getByLabel('Reason').fill('Waiting for the purchase order copy');
  await page.getByLabel('Next owner (user id)').fill('usr-sam-rivera');
  await page.getByRole('form', { name: 'Hold for more information' }).getByRole('button', { name: 'Hold for more information' }).click();
  await expect(page.getByTestId('hold-info')).toContainText('Waiting for the purchase order copy');

  await page.getByRole('group', { name: 'Case actions' }).getByRole('button', { name: 'Resume' }).click();
  await expect(page.getByTestId('hold-info')).toHaveCount(0);
  await expect(page.getByTestId('case-state')).toHaveText(afterOpen!);

  await page.getByRole('group', { name: 'Case actions' }).getByRole('button', { name: 'Evaluate policy' }).click();
  await page.getByRole('tab', { name: 'Decision' }).click();
  await expect(page).toHaveURL(/tab=decision/);
  const status = page.getByTestId('policy-status');
  await expect(status).toBeVisible();
  const view = await (await request.get('/api/cases/CHG-1042')).json();
  await expect(status).toHaveText(view.policy.status);

  await page.reload();
  await expect(page.getByTestId('policy-status')).toHaveText(view.policy.status);

  // Switch the demo role to cardholder through the real role endpoint (the page's cookie jar).
  const r = await page.request.post('/api/session/role', { data: { role: 'cardholder' } });
  expect(r.ok()).toBe(true);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Evaluate policy' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Hold for more information' })).toHaveCount(0);
});
