import type { ActionView, CaseView, StepOut } from '@/api';
import type { SlotState } from '@/design-system/primitives';

// Tolerant readers for fields a backend ticket is adding. Render if present; never invent.

export type CaseStepItem = { key: string; label: string; status: 'done' | 'current' | 'upcoming' | 'blocked' };
export function caseSteps(c: CaseView): CaseStepItem[] | null {
  const raw = (c as unknown as { steps?: unknown }).steps;
  if (!Array.isArray(raw)) return null;
  const ok = raw.filter((s): s is CaseStepItem => typeof s === 'object' && s !== null && typeof (s as CaseStepItem).key === 'string' && typeof (s as CaseStepItem).label === 'string');
  return ok.length ? ok : null;
}

/** `recovery_actions` entries the client can execute: full ActionView objects only (plain strings are not executable). */
export function recoveryActions(c: CaseView): ActionView[] {
  const raw = (c as unknown as { recovery_actions?: unknown }).recovery_actions;
  if (!Array.isArray(raw)) return [];
  return raw.filter((a): a is ActionView => typeof a === 'object' && a !== null && typeof (a as ActionView).command === 'string' && typeof (a as ActionView).idempotency_key === 'string');
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
  const replayedFlag = (s as unknown as { replayed?: unknown }).replayed === true;
  const mode = s.execution_mode ? s.execution_mode.toUpperCase() : null;
  const replayed = replayedFlag || (s.execution_mode === 'replay' && s.attempts > 1);
  const slot: SlotState = s.status === 'running' || s.status === 'queued' ? 'work' : s.status === 'failed' ? 'block' : s.status === 'succeeded' || s.status === 'completed' || s.status === 'done' ? 'done' : 'idle';
  return { mode, replayed, slot };
}
