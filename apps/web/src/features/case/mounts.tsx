// The one place feature modules are mounted into the case workspace (see registry.ts and each feature's README).
import { commandForms as moneyForms, MONEY_STEPS, MoneyTask } from '@/features/money';
import { COMMAND_FORMS } from './command-forms';
import type { CaseRegistry, CaseSlotProps } from './registry';

function MoneyBlock({ caseId, c, onSelectRecord }: CaseSlotProps) {
  return <MoneyTask caseId={caseId} c={c} onOpenRecord={onSelectRecord} />;
}

export const caseRegistry: CaseRegistry = {
  tabPanels: [],
  taskBlocks: [
    // Money steps (credit, tracks, dispute, card controls, closure): MoneyTask renders the server's actions itself.
    { key: 'money', match: (c) => MONEY_STEPS.has(c.step), Block: MoneyBlock, ownsActions: true },
  ],
  commandForms: { ...COMMAND_FORMS, ...moneyForms },
  rail: null,
};
