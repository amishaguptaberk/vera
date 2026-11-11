// The one place feature modules are mounted into the case workspace (see registry.ts and each feature's README).
import { CommsPanel, commandForms as commsForms, FollowupTask, isFollowupStep } from '@/features/comms';
import { CallPanel, CardholderVerifyPanel, commandForms as verifyForms, IdentityPanel } from '@/features/verify';
import { commandForms as moneyForms, MONEY_STEPS, MoneyTask } from '@/features/money';
import { COMMAND_FORMS } from './command-forms';
import type { CaseRegistry, CaseSlotProps } from './registry';

function MoneyBlock({ caseId, c, onSelectRecord }: CaseSlotProps) {
  return <MoneyTask caseId={caseId} c={c} onOpenRecord={onSelectRecord} />;
}

function CommsTab({ caseId }: CaseSlotProps) {
  return <CommsPanel caseId={caseId} />;
}
function FollowupBlock({ caseId }: CaseSlotProps) {
  return <FollowupTask caseId={caseId} />;
}
// The workspace ActionBar is visible above the tabs, so the verify panels do not repeat the actions.
function IdentityTab({ caseId, onSelectRecord }: CaseSlotProps) {
  return <IdentityPanel caseId={caseId} onOpenSource={onSelectRecord} showActions={false} />;
}
function CallTab({ caseId, onSelectRecord }: CaseSlotProps) {
  return <CallPanel caseId={caseId} onOpenSource={onSelectRecord} showActions={false} />;
}
function CardholderVerifyBlock({ caseId }: CaseSlotProps) {
  return <CardholderVerifyPanel caseId={caseId} />;
}

export const caseRegistry: CaseRegistry = {
  // Communications (prototype): messages, then the identity verification and verification call items.
  tabPanels: [
    { tab: 'comms', key: 'comms', Panel: CommsTab },
    { tab: 'comms', key: 'identity', Panel: IdentityTab },
    { tab: 'comms', key: 'call', Panel: CallTab },
  ],
  taskBlocks: [
    // Cardholder "Verify it's you" (step idv): the panel renders the code entry / push approve itself.
    { key: 'verify-cardholder', match: (c, role) => role === 'cardholder' && c.step === 'idv', Block: CardholderVerifyBlock, ownsActions: true },
    // Money steps (credit, tracks, dispute, card controls, closure): MoneyTask renders the server's actions itself.
    { key: 'money', match: (c) => MONEY_STEPS.has(c.step), Block: MoneyBlock, ownsActions: true },
    // Follow-up steps (draft → waiting → no response → response): actions stay in the generic ActionBar.
    { key: 'followup', match: (c) => isFollowupStep(c.step), Block: FollowupBlock, ownsActions: false },
  ],
  commandForms: { ...COMMAND_FORMS, ...commsForms, ...verifyForms, ...moneyForms },
  rail: null,
};
