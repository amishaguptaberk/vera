import type { ReactNode } from 'react';
import styles from './PageMain.module.css';

/** The page's main landmark with the prototype's page padding (the case workspace has its own, beside the rail). */
export function PageMain({ children }: { children: ReactNode }) {
  return <main className={styles.main}>{children}</main>;
}
