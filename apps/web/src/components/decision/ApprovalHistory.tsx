import styles from './Decision.module.css';

export type ApprovalHistoryItem = { id: string; status: string; reviewer?: string | null; at?: string | null; reason?: string | null };

/** Approval history rows under the packet. */
export function ApprovalHistory({ items }: { items: readonly ApprovalHistoryItem[] }) {
  if (!items.length) return null;
  return (
    <div className={styles.pk}>
      <div className={styles.pkK}>Approval history</div>
      <ul className={styles.hist}>
        {items.map((a) => (
          <li key={a.id}>
            {[a.id, a.status, a.reviewer, a.at].filter(Boolean).join(' · ')}
            {a.reason ? ` · “${a.reason}”` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}
