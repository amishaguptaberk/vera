import { RefChip } from '@/design-system/primitives';
import styles from './Money.module.css';

export type ClosureItemView = {
  key: string;
  label: string;
  /** Server status. `unknown` is never shown as met. */
  status: 'met' | 'unmet' | 'unknown';
  detail: string;
  owner_name: string | null;
  next_action: string | null;
  record_ids: readonly string[];
};

export type ClosureChecklistProps = {
  items: readonly ClosureItemView[] | null;
  /** Set when the endpoint is not deployed yet (404) or failed. */
  unavailable?: string | null;
  onOpenRecord?: (id: string) => void;
};

/** Prototype "Before closing" (.cl rows, ✓ box only for met items). */
export function ClosureChecklist({ items, unavailable, onOpenRecord }: ClosureChecklistProps) {
  return (
    <div data-testid="closure-checklist">
      <div className={styles.rl}>Before closing</div>
      {unavailable ? <p className={styles.fNote}>{unavailable}</p> : null}
      {(items ?? []).map((c) => {
        const ok = c.status === 'met';
        const open = !ok && (c.owner_name || c.next_action) ? [c.owner_name, c.next_action].filter(Boolean).join(' · ') : null;
        return (
          <div key={c.key} className={`${styles.cl}${ok ? ` ${styles.ok}` : ''}`} data-testid="closure-item" data-status={c.status}>
            <span className={styles.bx} data-mark aria-label={ok ? 'Met' : c.status === 'unknown' ? 'Not verifiable' : 'Open'}>
              {ok ? '✓' : ''}
            </span>
            <div>
              <div>
                {c.label}
                {c.record_ids.length && onOpenRecord ? (
                  <span className={styles.refs} data-ref>
                    {c.record_ids.map((id) => (
                      <RefChip key={id} onClick={() => onOpenRecord(id)}>
                        {id}
                      </RefChip>
                    ))}
                  </span>
                ) : null}
              </div>
              <div className={styles.cd}>
                {c.status === 'unknown' ? 'Not verifiable · ' : ''}
                {c.detail}
              </div>
              {open ? <div className={styles.cd}>{open}</div> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
