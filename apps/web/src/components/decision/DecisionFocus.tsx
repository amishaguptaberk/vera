import type { ReactNode } from 'react';
import styles from './Decision.module.css';

export type DecisionFocusProps = { id?: string; label: string; eyebrow: string; title: string; paras?: readonly string[]; children?: ReactNode };

/** The prototype's `.focus` decision card (eyebrow dot, title, paragraphs, body). */
export function DecisionFocus({ id, label, eyebrow, title, paras = [], children }: DecisionFocusProps) {
  return (
    <section className={styles.focus} id={id} aria-label={label} aria-live="polite">
      <div className={styles.focusIn}>
        <div className={styles.eyebrow}>
          <span className={styles.dot} aria-hidden="true" />
          <span className={styles.lbl}>{eyebrow}</span>
        </div>
        <h2 className={styles.title}>{title}</h2>
        {paras.map((p) => (
          <p key={p} className={styles.p}>
            {p}
          </p>
        ))}
        {children}
      </div>
    </section>
  );
}
