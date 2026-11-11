import type { ReactNode } from 'react';
import styles from './Money.module.css';

/** Prototype `.focus` task card shell (state label + title). CaseWorkspace owns the live one; previews use this. */
export function TaskFrame({ label, title, children }: { label: string; title: string; children: ReactNode }) {
  return (
    <section className={styles.focus} aria-label="Current task">
      <div className={styles.focusIn}>
        <div className={styles.fState}>
          <span>{label}</span>
        </div>
        <h2 className={styles.fTitle}>{title}</h2>
        {children}
      </div>
    </section>
  );
}
