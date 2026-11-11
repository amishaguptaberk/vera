'use client';

import { StatusSlot, type SlotState } from '@/design-system/primitives';
import styles from './Comms.module.css';
import type { CommsListRow, CommsTone } from './types';

const SLOT: Record<CommsTone, SlotState> = { ok: 'done', bad: 'block', cur: 'review', wait: 'wait', mute: 'idle' };

export type CommsListProps = { rows: readonly CommsListRow[]; onOpen: (id: string) => void };

/** Prototype `.cm-l` list (Main.dc.html:1741-1744). */
export function CommsList({ rows, onOpen }: CommsListProps) {
  if (!rows.length) return <p className={styles.rd}>No messages or calls yet.</p>;
  return (
    <ul className={styles.list}>
      {rows.map((r) => (
        <li key={r.id}>
          <button type="button" className={styles.item} onClick={() => onOpen(r.id)}>
            <span className={styles.k}>
              <StatusSlot state={SLOT[r.tone]} />
              {r.kind}
            </span>
            <span className={styles.it}>
              <span className={styles.in}>{r.title}</span>
              <span className={styles.st} data-tone={r.tone}>
                {r.status}
              </span>
            </span>
            <span className={styles.at}>{r.at}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
