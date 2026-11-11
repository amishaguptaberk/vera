// The one place feature modules are mounted into the case workspace (see registry.ts and each feature's README).
import { CommsPanel, commandForms as commsForms, FollowupTask, isFollowupStep } from '@/features/comms';
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

export const caseRegistry: CaseRegistry = {
  tabPanels: [{ tab: 'comms', key: 'comms', Panel: CommsTab }],
  taskBlocks: [
    // Money steps (credit, tracks, dispute, card controls, closure): MoneyTask renders the server's actions itself.
    { key: 'money', match: (c) => MONEY_STEPS.has(c.step), Block: MoneyBlock, ownsActions: true },
    // Follow-up steps (draft → waiting → no response → response): actions stay in the generic ActionBar.
    { key: 'followup', match: (c) => isFollowupStep(c.step), Block: FollowupBlock, ownsActions: false },
  ],
  commandForms: { ...COMMAND_FORMS, ...commsForms, ...moneyForms },
  rail: null,
};
