import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// No mocks. The whole CHG-1042 journey through the UI, as each role, on a real API + worker (replay mode, simulated
// providers): investigation → follow-up → cardholder reply with a PDF → analyst review (conflicting, receipt
// accepted) → identity (OTP read from the cardholder's demo outbox) → verification call with approved questions →
// related charges → policy eligible → decision packet → credit decision → reviewer approval → provisional credit →
// dispute track → card controls (card admin approves and applies) → final message → close → closed.
const setRole = async (page: Page, role: string) => expect((await page.request.post('/api/session/role', { data: { role } })).ok()).toBe(true);
const caseView = async (request: APIRequestContext) => (await request.get('/api/cases/CHG-1042')).json();
const stepOf = async (request: APIRequestContext) => (await caseView(request)).step as string;

test.setTimeout(300_000);

test('journey: report → investigation → cardholder → identity → call → decision → approval → credit → dispute → controls → final → closed', async ({ page, request }) => {
  expect((await request.post('/api/demo/reset')).ok()).toBe(true);
  const acts = page.getByRole('group', { name: 'Case actions' }).first();
  const state = page.getByTestId('case-state');

  await test.step('analyst opens the case and the specialists investigate', async () => {
    await setRole(page, 'analyst');
    await page.goto('/cases/CHG-1042');
    await acts.getByRole('button', { name: 'Open case' }).click();
    await acts.getByRole('button', { name: 'Start investigation' }).click();
    await expect(state).toHaveText('Investigation complete', { timeout: 60_000 });
  });

  await test.step('analyst drafts and sends the follow-up', async () => {
    const followup = page.getByTestId('task-block-followup');
    await followup.getByRole('button', { name: 'Draft follow-up' }).click();
    await page.getByRole('button', { name: 'Approve and send' }).click();
    await expect(state).toHaveText('Waiting on cardholder');
  });

  await test.step('cardholder replies with a PDF receipt', async () => {
    await setRole(page, 'cardholder');
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Confirm this charge' })).toBeVisible();
    await page.getByLabel('I did').check();
    await page.getByLabel('Attach file').setInputFiles({ name: 'receipt.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 receipt') });
    await expect(page.getByText('receipt.pdf')).toBeVisible();
    await page.getByRole('button', { name: 'Send response' }).click();
    await expect(page.getByText('Nothing is waiting for you right now.')).toBeVisible();
  });

  await test.step('analyst reviews: no grounded suggestion for this reply in replay, so the analyst decides alone', async () => {
    await setRole(page, 'analyst');
    await page.goto('/cases/CHG-1042');
    await expect(state).toHaveText('Needs review');
    // Replay holds a recording for the canonical reply text only; this reply gets an honest, calm note.
    await expect(page.getByTestId('review-suggestion')).toHaveText('Review suggestion unavailable — review the reply yourself.', { timeout: 30_000 });
    await expect(page.getByRole('alert').filter({ hasText: /\S/ })).toHaveCount(0);
    await acts.getByRole('button', { name: 'Review response' }).click();
    const form = page.getByRole('form', { name: 'Review response' });
    await form.getByLabel('Outcome').selectOption('conflicting');
    await form.getByLabel('Note').fill('The reply contradicts the initial report; the receipt itself is accepted.');
    await form.getByLabel('Accept the attached receipt as evidence').check();
    await form.getByRole('button', { name: 'Review response' }).click();
    await expect.poll(() => stepOf(request)).toBe('idv');
    await expect(state).toHaveText((await caseView(request)).state_label);
  });

  await test.step('identity: analyst sends a code; the cardholder reads it in the demo outbox and enters it', async () => {
    await acts.getByRole('button', { name: 'Send verification' }).click();
    const form = page.getByRole('form', { name: 'Send verification' });
    await form.getByLabel('Channel').selectOption('otp');
    await form.getByRole('button', { name: 'Send verification' }).click();
    await expect(form).toHaveCount(0);
    // The cardholder's home leads with the verification the server offers them.
    await setRole(page, 'cardholder');
    await page.goto('/');
    await expect(page.getByText('Verify your identity')).toBeVisible();
    const outbox = page.getByTestId('cardholder-demo-outbox');
    await expect(outbox).toContainText(/\b\d{6}\b/);
    const code = /\b(\d{6})\b/.exec((await outbox.textContent()) ?? '')![1]!;
    await page.getByLabel('6-digit code').fill(code);
    await page.getByRole('button', { name: 'Verify', exact: true }).click();
    await expect(page.getByText('Thanks — you’re verified.')).toBeVisible();
  });

  await test.step('analyst approves the default questions with consent, starts the call; answers come back cited', async () => {
    await setRole(page, 'analyst');
    await page.goto('/cases/CHG-1042');
    await expect.poll(() => stepOf(request)).toBe('verify');
    const call = page.getByTestId('task-block-call');
    await expect(call.getByText('Did you place the order with Northstar Equipment on the card ending 4418?')).toBeVisible();
    await call.getByRole('button', { name: 'Edit questions' }).click();
    await expect(call.getByLabel('Question 3')).toHaveValue('Did anyone else have access to your card?');
    const start = call.getByRole('button', { name: 'Start verification call' });
    await expect(start).toBeDisabled(); // consent first
    await call.getByLabel('Cardholder consented to this verification call').check();
    await start.click();
    await expect.poll(() => stepOf(request), { timeout: 60_000 }).toBe('packet');
    await page.getByRole('tab', { name: 'Communications' }).click();
    await expect(page.getByText('Verification call complete')).toBeVisible({ timeout: 30_000 });
    // Answers come back with the transcript line they cite; the approver is named.
    await expect(page.getByText('Sam Rivera ·', { exact: false }).first()).toBeVisible();
    await expect(page.getByText('usr-sam-rivera')).toHaveCount(0);
  });

  await test.step('analyst reviews both related charges from the evidence register', async () => {
    await page.getByRole('tab', { name: 'Evidence' }).click();
    for (const [id, reason] of [['CHG-1051', 'Separate Northstar order on its own PO.'], ['CHG-1048', 'Cleared last month; unrelated amount.']] as const) {
      const row = page.getByTestId(`review-${id}`);
      await row.getByRole('button', { name: 'Not related' }).click();
      const form = page.getByRole('form', { name: `Review ${id}` });
      await form.getByLabel('Reason').fill(reason);
      await form.getByRole('button', { name: 'Mark not related' }).click();
      await expect(page.getByTestId(`review-${id}`)).toHaveCount(0);
    }
    await expect(acts.getByRole('button', { name: 'Review related charge' })).toHaveCount(0);
  });

  await test.step('policy is eligible; the decision packet is prepared; the analyst records a credit decision and sends it to the reviewer', async () => {
    await acts.getByRole('button', { name: 'Evaluate policy' }).click();
    await page.getByRole('tab', { name: 'Decision' }).click();
    await expect(page.getByTestId('policy-status')).toHaveText('eligible');
    await acts.getByRole('button', { name: 'Prepare decision packet' }).click();
    await expect(page.getByTestId('decision-packet')).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => stepOf(request), { timeout: 30_000 }).toBe('decide');
    await acts.getByRole('button', { name: 'Record decision' }).click();
    const form = page.getByRole('form', { name: 'Record decision' });
    await form.getByLabel('Decision').selectOption('credit');
    await form.getByLabel('Your rationale').fill('Cardholder confirmed on the call that she did not authorize the charge.');
    await form.getByRole('button', { name: 'Record decision' }).click();
    await expect(form).toHaveCount(0);
    await acts.getByRole('button', { name: 'Send to reviewer' }).click();
    await expect.poll(() => stepOf(request)).toBe('waitrv');
    await expect(state).toHaveText('Waiting on reviewer');
  });

  await test.step('reviewer approves', async () => {
    await setRole(page, 'reviewer');
    await page.goto('/cases/CHG-1042');
    await page.getByTestId('task-block-reviewer').getByRole('button', { name: 'Approve decision' }).click();
    await expect.poll(() => stepOf(request)).toBe('issue');
  });

  await test.step('analyst issues the provisional credit', async () => {
    await setRole(page, 'analyst');
    await page.goto('/cases/CHG-1042');
    await expect(state).toHaveText('Approved · credit ready');
    await page.getByTestId('task-block-money').getByRole('button', { name: 'Issue temporary credit — simulated' }).click();
    await expect.poll(() => stepOf(request)).not.toBe('issue');
    await expect(page.getByText('Temporary credit issued — pending, not deducted.')).toBeVisible();
  });

  await test.step('dispute track and card controls, one server-focused step at a time (card admin approves and applies)', async () => {
    const money = page.getByTestId('task-block-money');
    // A specialist (Prevention Planner, Dispute Packet Preparer) may record its result in the background between
    // loading the page and clicking: the UI then says the case changed and shows the latest version, and the loop
    // reads the step again, as a user would.
    const stale = page.getByText('This case changed while you were viewing it.');
    const click = async (role: string, name: string) => {
      const before = (await caseView(request)).case_version;
      await money.getByRole('button', { name }).click();
      await expect
        .poll(async () => (await stale.count()) > 0 || (await caseView(request)).case_version > before, { timeout: 15_000 })
        .toBe(true);
      if (role !== 'analyst') await setRole(page, 'analyst');
    };
    const seen: string[] = [];
    for (let i = 0; i < 16; i++) {
      await setRole(page, 'analyst');
      const step = await stepOf(request);
      seen.push(step);
      if (step === 'finalprep') break;
      if (step === 'waitctl' || step === 'ctl_apply') {
        await setRole(page, 'card_admin');
        await page.goto('/cases/CHG-1042');
        await click('card_admin', step === 'waitctl' ? 'Approve controls' : 'Apply approved controls — simulated');
        continue;
      }
      await page.goto('/cases/CHG-1042');
      await expect(state).toHaveText((await caseView(request)).state_label);
      if (step === 'controls') await click('analyst', 'Send control plan');
      else if (step === 'ctl_prep') {
        // No recommendation reached this step: the analyst chooses the controls.
        await money.getByRole('checkbox', { name: 'Lock card' }).check();
        await money.getByRole('checkbox', { name: 'Replace card' }).check();
        await click('analyst', 'Send control plan');
      } else if (step === 'dsp_prepare') await click('analyst', 'Prepare dispute packet');
      else if (step === 'dsp_open') {
        // The Dispute Packet Preparer records its narrative in the background; the view reloads when it lands.
        await expect(page.getByTestId('dispute-narrative')).toHaveAttribute('data-status', 'ready', { timeout: 30_000 });
        await page.waitForLoadState('networkidle');
        await click('analyst', 'Open dispute packet');
      }
      else if (step === 'dsp_review') {
        await expect(page.getByTestId('dispute-narrative')).toHaveAttribute('data-status', 'ready', { timeout: 30_000 });
        await expect(page.getByRole('button', { name: 'Retry dispute narrative' })).toHaveCount(0);
        await click('analyst', 'Mark reviewed');
      } else if (step === 'dsp_submit') await click('analyst', 'Record submission — simulated');
      else throw new Error(`unexpected step ${step} after ${seen.join(' → ')}`);
    }
    expect(seen.at(-1)).toBe('finalprep');
    expect(seen).toEqual(expect.arrayContaining(['dsp_prepare', 'dsp_open', 'dsp_review', 'dsp_submit']));
  });

  await test.step('analyst drafts and sends the final message, then closes; the simulated dispute outcome closes the case', async () => {
    await setRole(page, 'analyst');
    await page.goto('/cases/CHG-1042');
    const money = page.getByTestId('task-block-money');
    await money.getByRole('button', { name: 'Draft final update' }).click();
    await expect.poll(() => stepOf(request)).toBe('final');
    await money.getByRole('button', { name: 'Send final update' }).click();
    await expect.poll(() => stepOf(request)).toBe('close');
    await expect(state).toHaveText('Ready to close');
    await money.getByRole('button', { name: /^Close case/ }).click();
    const form = page.getByRole('form', { name: /^Close case/ });
    await form.getByLabel('Reason').fill('Provisional credit issued; dispute submitted; controls applied.');
    await form.getByLabel('Outcome').selectOption('resolved');
    await form.getByRole('button', { name: /^Close case/ }).click();
    await expect.poll(() => stepOf(request)).toBe('monitoring');
    await expect(state).toHaveText('Monitoring');
    const demo = page.getByTestId('dispute-outcome-demo');
    await demo.getByText('Demo controls · dispute outcome').click();
    await demo.getByRole('button', { name: 'Dispute won' }).click();
    await expect(state).toHaveText('Closed', { timeout: 30_000 });
    await page.reload();
    await expect(state).toHaveText('Closed');
    await expect(page.getByText(/^All \d+ steps complete$/)).toBeVisible();
    // Closed: no list of refused actions, no actions at all.
    await expect(page.getByText('The case is closed. No further actions can run.')).toHaveCount(0);
    await expect(page.getByRole('group', { name: 'Case actions' })).toHaveCount(0);
  });
});
