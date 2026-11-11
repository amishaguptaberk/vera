import type { ActionView, CaseView, StepOut } from '@/api';
import type { SlotState } from '@/design-system/primitives';

// Tolerant readers for fields a backend ticket is adding. Render if present; never invent.

export function caseSteps(c: CaseView): CaseView['steps'] | null {
  return c.steps.length ? c.steps : null;
}

/** The server's recovery actions (ActionView[]), in order. */
export function recoveryActions(c: CaseView): ActionView[] {
  return c.recovery_actions ?? [];
}

/** State kind → the prototype's status slot. */
export function slotFor(kind: CaseView['state_kind']): SlotState {
  return kind === 'working' ? 'work' : kind === 'waiting' ? 'wait' : kind === 'blocked' ? 'block' : kind === 'complete' ? 'done' : kind === 'review' ? 'review' : 'idle';
}

export function taskLabel(kind: CaseView['state_kind']): string {
  return kind === 'complete' ? 'Outcome' : kind === 'working' ? 'In progress' : kind === 'waiting' ? 'While you wait' : 'Your next step';
}

export const AUTHORED_REFERENCE = 'authored-reference';

/** How a run step is labelled in Run details. Values are the server's; only the wording is chosen here. */
export function stepLabels(s: StepOut): { mode: string | null; replayed: boolean; slot: SlotState } {
  const mode = s.execution_mode ? s.execution_mode.toUpperCase() : null;
  const replayed = s.replayed === true;
  const slot: SlotState = s.status === 'running' || s.status === 'queued' ? 'work' : s.status === 'failed' ? 'block' : s.status === 'succeeded' || s.status === 'completed' || s.status === 'done' ? 'done' : 'idle';
  return { mode, replayed, slot };
}
