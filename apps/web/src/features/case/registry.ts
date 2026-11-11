// Mounting points of the case workspace. A feature module is mounted with one import + one entry in `mounts.tsx`;
// CaseWorkspace renders whatever is registered and an honest "Not available yet" state for an empty slot.
// The registry never decides which actions exist: blocks receive the server's CaseView and render its actions.
import type { ComponentType } from 'react';
import type { CaseView } from '@/api';
import type { FormField } from './command-forms';

export type CaseRole = 'analyst' | 'cardholder' | 'reviewer';

/** What every mounted block receives. `sel` / `onSelectRecord` are the Evidence selection (URL state). */
export type CaseSlotProps = {
  caseId: string;
  c: CaseView;
  role: CaseRole | null;
  sel: string | null;
  onSelectRecord: (recordId: string) => void;
};

/** The prototype's case tabs (Main.dc.html `etabs`): fixed order and labels. Panels are registered per key. */
export const CASE_TABS = [
  { id: 'evidence', label: 'Evidence' },
  { id: 'comms', label: 'Communications' },
  { id: 'decision', label: 'Decision' },
  { id: 'trace', label: 'Run details' },
] as const;
export type CaseTabId = (typeof CASE_TABS)[number]['id'];

/** A panel rendered inside one of the prototype's tabs. Several panels may share a tab; they stack in order. */
export type TabPanelMount = { tab: CaseTabId; key: string; Panel: ComponentType<CaseSlotProps> };

/**
 * A task-card body for some workflow steps. `ownsActions` blocks render the server's available_actions
 * themselves (their payloads come from the block's own inputs), so the generic ActionBar is not shown.
 */
export type TaskBlockMount = {
  key: string;
  match: (c: CaseView, role: CaseRole | null) => boolean;
  Block: ComponentType<CaseSlotProps>;
  ownsActions: boolean;
  /** The block renders the task title itself (a more specific one than the server's next action), so the card shows one. */
  ownsTitle?: boolean;
  /** Commands the block runs itself (its own button), left out of the generic ActionBar so nothing shows twice. */
  hides?: (c: CaseView) => readonly string[];
};

export type RailProps = CaseSlotProps & { open: boolean; onClose: () => void; onNavigate: (target: string) => void };
/** The rail and whether this role has one (the shell shows its top-bar toggle only then). */
export type RailMount = { Rail: ComponentType<RailProps>; available: (role: CaseRole | null) => boolean };

export type CaseRegistry = {
  tabPanels: readonly TabPanelMount[];
  taskBlocks: readonly TaskBlockMount[];
  commandForms: Readonly<Record<string, readonly FormField[]>>;
  rail: RailMount | null;
};

export const panelsFor = (r: CaseRegistry, tab: CaseTabId) => r.tabPanels.filter((p) => p.tab === tab);
export const taskBlockFor = (r: CaseRegistry, c: CaseView, role: CaseRole | null) => r.taskBlocks.find((b) => b.match(c, role)) ?? null;
