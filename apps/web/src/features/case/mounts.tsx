// The one place feature modules are mounted into the case workspace (see registry.ts).
import { COMMAND_FORMS } from './command-forms';
import type { CaseRegistry } from './registry';

export const caseRegistry: CaseRegistry = {
  tabPanels: [],
  taskBlocks: [],
  commandForms: { ...COMMAND_FORMS },
  rail: null,
};
