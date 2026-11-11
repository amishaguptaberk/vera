import { expect, test } from '@playwright/test';

// No mocks: every request goes through the app's /api rewrite to the real backend (VERA_API_ORIGIN).
// Known-good demo journey: reset → queue → open CHG-1042 → Start investigation → 3 specialist steps succeed →
// Evidence (6 findings, 2 open conflicts, receipt missing) → Run details REPLAY · authored-reference · v1 →
// policy blocked → material change (conflict stale, policy re-evaluated) → hold / resume → cardholder view.
test('known-good journey: CHG-1042 investigation → evidence → run details → policy → material change → hold/resume → cardholder', async ({ page, request }) => {
  expect((await request.post('/api/demo/reset')).ok()).toBe(true);
  expect((await page.request.post('/api/session/role', { data: { role: 'analyst' } })).ok()).toBe(true);
  await page.goto('/cases');
  await page.getByRole('link', { name: 'CHG-1042 · Northstar Equipment' }).click();
  await expect(page).toHaveURL(/\/cases\/CHG-1042/);
  await expect(page.getByTestId('case-state')).toHaveText('New report');

  const acts = page.getByRole('group', { name: 'Case actions' });
  const primary = acts.locator('[data-primary="true"]');
  await expect(primary).toHaveText('Open case');
  await primary.click();
  await expect(page.getByTestId('case-state')).not.toHaveText('New report');

  // Start investigation (server-offered after open) → the worker runs three specialist steps in replay.
  await acts.getByRole('button', { name: 'Start investigation' }).click();
  await page.getByRole('tab', { name: 'Run details' }).click();
  const run = page.getByTestId('run').first();
  await expect(run).toBeVisible({ timeout: 30_000 });
  for (const step of ['charge_investigator', 'receipt_document_reviewer', 'related_transaction_investigator']) {
    const row = run.getByTestId(`step-${step}`);
    await expect(row).toContainText('succeeded', { timeout: 30_000 });
    await expect(row).toContainText('REPLAY');
    await expect(row).toContainText('authored-reference');
    await expect(row).toContainText('v1');
  }
  await expect(run).toContainText('REPLAY');

  // Evidence register from the real API.
  await page.getByRole('tab', { name: 'Evidence' }).click();
  const register = page.getByTestId('evidence-register');
  await expect(register.getByRole('list', { name: 'Findings' }).getByRole('listitem')).toHaveCount(6);
  await expect(register.getByRole('list', { name: 'Open conflicts' }).getByRole('listitem')).toHaveCount(2);
  await expect(register.getByRole('list', { name: 'Missing evidence' })).toContainText('Receipt');

  // Policy: blocked.
  await page.getByRole('tab', { name: 'Decision' }).click();
  await expect(page).toHaveURL(/tab=decision/);
  await expect(page.getByTestId('policy-status')).toHaveText('blocked');

  // Demo material change: DLV-882 v2 → the purchase-records check goes stale, a conflict drops, policy re-evaluated.
  await page.getByText('Demo controls').click();
  await page.getByRole('button', { name: 'Simulate material change' }).click();
  await expect(page.getByText(/New version v2/)).toBeVisible();
  await expect(page.getByText(/stale checks: .*purchase_records/)).toBeVisible();
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(register.getByRole('list', { name: 'Open conflicts' }).getByRole('listitem')).toHaveCount(1);
  await register.getByRole('button', { name: 'DLV-882', exact: true }).click();
  await expect(page).toHaveURL(/sel=DLV-882/);
  await expect(page.getByTestId('version-2')).toBeVisible();
  await expect(page.getByTestId('version-1')).toContainText('superseded');
  await page.getByRole('tab', { name: 'Decision' }).click();
  const after = await (await request.get('/api/cases/CHG-1042')).json();
  expect(after.policy).toBeTruthy();
  await expect(page.getByTestId('policy-status')).toHaveText(after.policy.status);

  // Hold / resume.
  const afterInv = await page.getByTestId('case-state').textContent();
  await acts.getByRole('button', { name: 'Hold for more information' }).click();
  await page.getByLabel('Reason').fill('Waiting for the purchase order copy');
  await page.getByLabel('Next owner (user id)').fill('usr-sam-rivera');
  await page.getByRole('form', { name: 'Hold for more information' }).getByRole('button', { name: 'Hold for more information' }).click();
  await expect(page.getByTestId('hold-info')).toContainText('Waiting for the purchase order copy');
  await page.getByRole('group', { name: 'Case actions' }).getByRole('button', { name: 'Resume' }).click();
  await expect(page.getByTestId('hold-info')).toHaveCount(0);
  await expect(page.getByTestId('case-state')).toHaveText(afterInv!);

  // Cardholder: no analyst actions and no internal tabs (server 403s the internal reads).
  const r = await page.request.post('/api/session/role', { data: { role: 'cardholder' } });
  expect(r.ok()).toBe(true);
  await page.goto('/cases/CHG-1042');
  await expect(page.getByTestId('case-state')).toBeVisible();
  for (const name of ['Evaluate policy', 'Hold for more information', 'Start investigation', 'Reassign']) {
    await expect(page.getByRole('button', { name })).toHaveCount(0);
  }
  for (const name of ['Evidence', 'Communications', 'Decision', 'Run details']) await expect(page.getByRole('tab', { name })).toHaveCount(0);
  await expect(page.getByTestId('policy-block')).toHaveCount(0);
  // Leave the shared demo session as the analyst.
  await page.request.post('/api/session/role', { data: { role: 'analyst' } });
});
