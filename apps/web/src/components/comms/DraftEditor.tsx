'use client';

import { useId } from 'react';
import { Button } from '@/design-system/primitives';
import styles from './Comms.module.css';

export type DraftChannel = 'email' | 'portal';
export const CHANNEL_LABELS: Readonly<Record<DraftChannel, string>> = { email: 'Email', portal: 'Ramp app' };

export type DraftEditorProps = {
  to: string;
  subject: string;
  body: string;
  channel: DraftChannel;
  /** Shown under the editor, e.g. "Edited · not saved" / "Saved as version 2". */
  savedNote?: string | null;
  /** Send is rendered only as the server offers it: null = not offered (disabled with reason). */
  send: { label: string; enabled: boolean; blockedReason?: string | null } | null;
  /** Save is offered when the server offers `update_communication_draft`. */
  canSave: boolean;
  busy?: boolean;
  error?: string | null;
  onChange: (next: { subject?: string; body?: string; channel?: DraftChannel }) => void;
  onSave: () => void;
  onSend: () => void;
};

/** Prototype task-card draft block (Main.dc.html:1635-1640) + send confirmation fields (channel, subject). */
export function DraftEditor(p: DraftEditorProps) {
  const id = useId();
  return (
    <div className={styles.draft}>
      <div className={styles.fact}>
        <span className={styles.fk}>To</span>
        <span>{p.to}</span>
        <span />
      </div>
      <div className={styles.field}>
        <span id={`${id}-ch`} className={styles.rd}>
          Channel
        </span>
        <div className={styles.chan} role="radiogroup" aria-labelledby={`${id}-ch`}>
          {(Object.keys(CHANNEL_LABELS) as DraftChannel[]).map((c) => (
            <button key={c} type="button" role="radio" aria-checked={p.channel === c} className={styles.optb} onClick={() => p.onChange({ channel: c })}>
              {CHANNEL_LABELS[c]}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.field}>
        <label htmlFor={`${id}-s`}>Subject</label>
        <input id={`${id}-s`} className={styles.control} value={p.subject} onChange={(e) => p.onChange({ subject: e.target.value })} />
      </div>
      <div className={styles.field}>
        <label htmlFor={`${id}-b`}>Message</label>
        <textarea id={`${id}-b`} className={`${styles.control} ${styles.ta}`} value={p.body} onChange={(e) => p.onChange({ body: e.target.value })} />
      </div>
      {p.error ? (
        <div className={styles.rd} role="alert">
          {p.error}
        </div>
      ) : null}
      <div className={styles.acts}>
        <Button variant="go" disabled={!p.send || !p.send.enabled || p.busy} onClick={p.onSend}>
          {p.send?.label ?? 'Approve and send'}
        </Button>
        {p.canSave ? (
          <Button disabled={p.busy} onClick={p.onSave}>
            Save draft
          </Button>
        ) : null}
        {p.savedNote ? <span className={styles.saved}>{p.savedNote}</span> : null}
      </div>
      {!p.send ? <p className={styles.safe}>Sending isn’t available for this case right now.</p> : p.send.blockedReason && !p.send.enabled ? <p className={styles.safe}>{p.send.blockedReason}</p> : null}
    </div>
  );
}
