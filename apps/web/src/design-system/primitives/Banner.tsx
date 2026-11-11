import type { ReactNode } from 'react';
import { Button } from './Button';
import styles from './Banner.module.css';

export type BannerProps = {
  tone?: 'info' | 'warn' | 'bad' | 'ok';
  title?: string;
  children: ReactNode;
  action?: { label: string; onClick: () => void };
};

/** Inline notice. `bad` announces assertively (role=alert); the rest are polite status messages. */
export function Banner({ tone = 'info', title, children, action }: BannerProps) {
  return (
    <div className={`${styles.banner} ${styles[tone]}`} role={tone === 'bad' ? 'alert' : 'status'}>
      <div className={styles.text}>
        {title ? <span className={styles.title}>{title} </span> : null}
        {children}
      </div>
      {action ? (
        <Button variant="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </div>
  );
}
