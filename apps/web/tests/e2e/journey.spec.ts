import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// No mocks. Continues the CHG-1042 journey through the UI as far as the merged backend serves it:
// follow-up draft → send → cardholder reply with an attachment → analyst review. Later stages are asserted only
// when the server offers them (annotated otherwise).
const setRole = async (page: Page, role: string) => expect((await page.request.post('/api/session/role', { data: { role } })).ok()).toBe(true);
const caseView = async (request: APIRequestContext) => (await request.get('/api/cases/CHG-1042')).json();

test('journey: follow-up → cardholder reply with attachment → analyst review', async ({ page, request }) => {
  expect((await request.post('/api/demo/reset')).ok()).toBe(true);
  await setRole(page, 'analyst');
  await page.goto('/cases/CHG-1042');
  const acts = page.getByRole('group', { name: 'Case actions' });
  await acts.getByRole('button', { name: 'Open case' }).click();
  await acts.getByRole('button', { name: 'Start investigation' }).click();
  await expect(page.getByTestId('case-state')).toHaveText('Investigation complete', { timeout: 30_000 });

  // Draft step: the editor owns save/send; the ActionBar does not repeat them.
  await acts.getByRole('button', { name: 'Draft follow-up' }).click();
  const send = page.getByRole('button', { name: 'Approve and send' });
  await expect(send).toBeVisible();
  await expect(acts.getByRole('button', { name: 'Approve and send' })).toHaveCount(0);
  await send.click();
  await expect(page.getByTestId('case-state')).toHaveText('Waiting on cardholder');

  // Refresh resumes the same state.
  await page.reload();
  await expect(page.getByTestId('case-state')).toHaveText('Waiting on cardholder');

  // Cardholder: lands on their own request (server-resolved), answers, attaches a receipt.
  await setRole(page, 'cardholder');
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Confirm this charge' })).toBeVisible();
  await page.getByLabel('I did').check();
  await page.getByLabel('Attach file').setInputFiles({ name: 'receipt.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 receipt') });
  await expect(page.getByText('receipt.pdf')).toBeVisible();
  await page.getByRole('button', { name: 'Send response' }).click();
  await expect(page.getByText('Nothing is waiting for you right now.')).toBeVisible();

  // Analyst reviews the response.
  await setRole(page, 'analyst');
  await page.goto('/cases/CHG-1042');
  await expect(page.getByTestId('case-state')).toHaveText('Needs review');
  await acts.getByRole('button', { name: 'Review response' }).click();
  await page.getByLabel('Outcome (complete, incomplete or conflicting)').fill('complete');
  await page.getByRole('form', { name: 'Review response' }).getByRole('button', { name: 'Review response' }).click();
  await expect(page.getByTestId('case-state')).not.toHaveText('Needs review');
  const after = await caseView(request);
  await expect(page.getByTestId('case-state')).toHaveText(after.state_label);
  test.info().annotations.push({ type: 'reached', description: `${after.state} / ${after.step}: ${after.available_actions.map((a: { command: string }) => a.command).join(', ')}` });
});
