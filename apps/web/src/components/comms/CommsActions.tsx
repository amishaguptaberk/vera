'use client';

import { Button } from '@/design-system/primitives';
import styles from './Comms.module.css';
import type { CommsAction } from './types';

export type CommsActionsProps = { actions: readonly CommsAction[]; busy?: string | null; safe?: string | null; onAction: (command: string) => void };

/** The `.acts` row of the message detail: exactly the server-offered actions; index 0 is the primary. */
export function CommsActions({ actions, busy = null, safe = null, onAction }: CommsActionsProps) {
  const blocked = actions.filter((a) => !a.enabled && a.blockedReason);
  return (
    <>
      {actions.length ? (
        <div className={styles.acts} role="group" aria-label="Message actions">
          {actions.map((a, i) => (
            <Button
              key={a.command}
              variant={i === 0 ? ['sm', 'go'] : a.ghost ? ['sm', 'ghost'] : 'sm'}
              disabled={!a.enabled || busy !== null}
              aria-busy={busy === a.command || undefined}
              onClick={() => onAction(a.command)}
            >
              {a.label}
            </Button>
          ))}
        </div>
      ) : null}
      {blocked.length ? (
        <ul className={styles.blocked} aria-label="Unavailable actions">
          {blocked.map((b) => (
            <li key={b.command}>
              <strong>{b.label}</strong> · {b.blockedReason}
            </li>
          ))}
        </ul>
      ) : null}
      {safe ? <p className={styles.safe}>{safe}</p> : null}
    </>
  );
}
