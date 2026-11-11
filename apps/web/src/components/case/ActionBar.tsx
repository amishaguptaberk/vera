'use client';

import type { components } from '@/api/schema';
import { Button } from '@/design-system/primitives';
import styles from './ActionBar.module.css';

type ActionView = components['schemas']['ActionView'];
type BlockedAction = components['schemas']['BlockedAction'];

export type ActionBarProps = {
  actions: readonly ActionView[];
  blocked: readonly BlockedAction[];
  busy?: string | null;
  onAction: (action: ActionView) => void;
};

/**
 * Exactly the server's `available_actions`. The last server-styled primary action (the current step's) is the one main button
 * and leads the row, as in the prototype; the others follow in server order. With no primary-styled action (a task
 * block owns the main action, e.g. the draft editor's Send) nothing is emphasised. Blocked reasons render inline.
 */
export function ActionBar({ actions, blocked, busy = null, onAction }: ActionBarProps) {
  const reasons = [
    ...actions.filter((a) => !a.enabled && a.blocked_reason).map((a) => ({ key: a.command, label: a.label, reason: a.blocked_reason! })),
    ...blocked.map((b) => ({ key: `b-${b.command}`, label: b.label, reason: b.blocked_reason })),
  ];
  // The server appends the current step's actions after the case-wide ones, so its last primary is the step's.
  const lead = actions.map((a) => a.style).lastIndexOf('primary');
  const ordered = lead > 0 ? [actions[lead], ...actions.filter((_, i) => i !== lead)] : actions;
  const safe = ordered[0]?.enabled ? ordered[0].safe_note : null;
  return (
    <div className={styles.wrap}>
      {actions.length ? (
        <div className={styles.acts} role="group" aria-label="Case actions">
          {ordered.map((a, i) => {
            const primary = i === 0 && lead >= 0;
            return (
            <Button
              key={a.command}
              variant={primary ? 'go' : a.style === 'ghost' ? 'ghost' : 'default'}
              data-primary={primary ? 'true' : undefined}
              disabled={!a.enabled || busy !== null}
              aria-busy={busy === a.command || undefined}
              onClick={() => onAction(a)}
            >
              {a.label}
            </Button>
            );
          })}
        </div>
      ) : null}
      {safe ? <p className={styles.safe}>{safe}</p> : null}
      {reasons.length ? (
        <ul className={styles.blocked} aria-label="Unavailable actions">
          {reasons.map((r) => (
            <li key={r.key}>
              <strong>{r.label}</strong> · {r.reason}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
