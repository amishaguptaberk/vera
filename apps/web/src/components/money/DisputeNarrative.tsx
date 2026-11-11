import { Button, RefChip } from '@/design-system/primitives';
import styles from './Money.module.css';

export type NarrativeStatement = { text: string; record_id: string; version: number; field: string };

export type DisputeNarrativeProps = {
  /** Server `narrative_status` of the dispute packet. */
  status: 'pending' | 'ready' | 'failed';
  reasonCode?: string | null;
  statements: readonly NarrativeStatement[];
  /** Label of the server-offered retry action, when the server offers it. */
  retryLabel?: string | null;
  onRetry?: () => void;
  busy?: boolean;
  onOpenRecord?: (id: string) => void;
};

// Display names for the server's reason_code values.
const REASON_LABEL: Record<string, string> = {
  unauthorized: 'Unauthorized',
  goods_not_received: 'Goods not received',
  quantity_mismatch: 'Quantity mismatch',
  amount_mismatch: 'Amount mismatch',
  duplicate: 'Duplicate',
};

/** Dispute Packet Preparer output on the packet: reason code and statements, each citing one record value. */
export function DisputeNarrative({ status, reasonCode, statements, retryLabel, onRetry, busy, onOpenRecord }: DisputeNarrativeProps) {
  if (status === 'pending') {
    return (
      <div className={styles.fNote} data-testid="dispute-narrative" data-status="pending" role="status">
        Preparing dispute narrative…
      </div>
    );
  }
  if (status === 'failed') {
    return (
      <div data-testid="dispute-narrative" data-status="failed">
        <div className={styles.err}>The dispute narrative could not be prepared. The packet can still be opened, reviewed and submitted.</div>
        {retryLabel && onRetry ? (
          <Button variant="ghost" disabled={busy} onClick={onRetry}>
            {retryLabel}
          </Button>
        ) : null}
      </div>
    );
  }
  return (
    <div data-testid="dispute-narrative" data-status="ready">
      <div className={styles.rl}>Dispute reason</div>
      <div className={styles.fact}>
        <span className={styles.k}>Reason code</span>
        <span>{reasonCode ? (REASON_LABEL[reasonCode] ?? reasonCode) : '—'}</span>
        <span />
      </div>
      <ul className={styles.narr} aria-label="Dispute narrative">
        {statements.map((s) => (
          <li key={`${s.record_id}:${s.field}:${s.text}`} className={styles.narrS}>
            <span>{s.text}</span>
            <span data-ref className={styles.refs}>
              <RefChip onClick={onOpenRecord ? () => onOpenRecord(s.record_id) : undefined} title={`${s.record_id} · v${s.version} · ${s.field}`}>
                {s.record_id} v{s.version} · {s.field}
              </RefChip>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
