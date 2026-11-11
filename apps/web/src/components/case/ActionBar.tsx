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

/** Exactly the server's `available_actions`, in order. Index 0 is the only primary. Blocked reasons render inline. */
export function ActionBar({ actions, blocked, busy = null, onAction }: ActionBarProps) {
  const reasons = [
    ...actions.filter((a) => !a.enabled && a.blocked_reason).map((a) => ({ key: a.command, label: a.label, reason: a.blocked_reason! })),
    ...blocked.map((b) => ({ key: `b-${b.command}`, label: b.label, reason: b.blocked_reason })),
  ];
  const safe = actions[0]?.enabled ? actions[0].safe_note : null;
  return (
    <div className={styles.wrap}>
      {actions.length ? (
        <div className={styles.acts} role="group" aria-label="Case actions">
          {actions.map((a, i) => (
            <Button
              key={a.command}
              variant={i === 0 ? 'go' : a.style === 'ghost' ? 'ghost' : 'default'}
              data-primary={i === 0 ? 'true' : undefined}
              disabled={!a.enabled || busy !== null}
              aria-busy={busy === a.command || undefined}
              onClick={() => onAction(a)}
            >
              {a.label}
            </Button>
          ))}
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
