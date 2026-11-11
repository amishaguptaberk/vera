import styles from './pages.module.css';

/** The prototype's cardholder card with an honest empty state (no fixture data). */
export function NotAvailableYet({ title = 'Not available yet.', children }: { title?: string; children: string }) {
  return (
    <div className={styles.ctask} data-testid="slot-empty">
      <div className={styles.card}>
        <b>{title}</b>
        <p>{children}</p>
      </div>
    </div>
  );
}
