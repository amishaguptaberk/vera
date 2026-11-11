import styles from './Money.module.css';

export type FinalDraftProps = { to: string; value: string; error: string | null; onChange: (v: string) => void };

/** Prototype final-update draft: To row + "Message" textarea; content-policy errors (server 422) inline. */
export function FinalDraft({ to, value, error, onChange }: FinalDraftProps) {
  return (
    <div className={styles.draft}>
      <div className={styles.fact}>
        <span className={styles.k}>To</span>
        <span>{to}</span>
        <span />
      </div>
      <div className={styles.field}>
        <label htmlFor="draft-body">Message</label>
        <textarea id="draft-body" className={styles.ta} value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={error ? true : undefined} aria-describedby={error ? 'draft-err' : undefined} />
      </div>
      {error ? (
        <div className={styles.err} id="draft-err" role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}
