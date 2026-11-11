export { commandForms } from './command-forms';
export type * from './contract';
export { MONEY_STEPS, MoneyTask, type MoneyTaskProps } from './MoneyTask';
export { closureChecklistQuery, executionsQuery, useClosureChecklist, useExecutions } from './queries';

/** No new case-workspace tabs: the money screens render inside the task region. */
export const tabs: readonly { key: string; label: string; Panel: () => null }[] = [];
