import { useId, useState } from 'react';
import { Button } from '@/design-system/primitives';
import styles from './Decision.module.css';

export type ServerButton = { label: string; enabled: boolean; blocked_reason?: string | null };

export type ReviewerControlsProps = {
  /** Server-offered approve action, or null when the server does not offer it. */
  approve: ServerButton | null;
  /** Server-offered return action, or null. */
  ret: ServerButton | null;
  stale: boolean;
  staleWhat?: string | null;
  analystName?: string;
  busy?: boolean;
  error?: string | null;
  onApprove: () => void;
  onReturn: (reason: string) => void;
};

/** Reviewer approve / return (prototype #rv-decision `rv.canDecide` block). Approve is disabled while stale. */
export function ReviewerControls({ approve, ret, stale, staleWhat, analystName = 'the analyst', busy = false, error, onApprove, onReturn }: ReviewerControlsProps) {
  const [note, setNote] = useState('');
  const id = useId();
  if (!approve && !ret) return null;
  return (
    <div className={styles.rule}>
      {stale ? (
        <div className={styles.err} role="alert">
          Evidence changed after this packet was sent{staleWhat ? ` (${staleWhat})` : ''}. Approval is blocked until {analystName} refreshes the packet. You can
          return it with a note.
        </div>
      ) : null}
      {approve ? (
        <div className={styles.acts}>
          <Button variant="go" onClick={onApprove} disabled={stale || !approve.enabled || busy}>
            {approve.label}
          </Button>
        </div>
      ) : null}
      {ret ? (
        <>
          <div className={styles.field}>
            <label htmlFor={id}>Or return it to {analystName} with a note</label>
            <textarea id={id} className={styles.ta} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          {error ? <div className={styles.err}>{error}</div> : null}
          <Button variant="sm" onClick={() => onReturn(note.trim())} disabled={!note.trim() || !ret.enabled || busy}>
            {ret.label}
          </Button>
        </>
      ) : error ? (
        <div className={styles.err}>{error}</div>
      ) : null}
    </div>
  );
}
