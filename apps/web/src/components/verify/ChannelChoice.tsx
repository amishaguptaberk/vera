import styles from './Verify.module.css';

export type ChannelOption = { key: string; label: string; sub: string };

/** Verification channel radiogroup (prototype `.idv-ch`). */
export function ChannelChoice({ options, value, onChange }: { options: readonly ChannelOption[]; value: string; onChange: (key: string) => void }) {
  return (
    <>
      <div className={styles.rl}>Channel</div>
      <div className={styles.chs} role="radiogroup" aria-label="Verification channel">
        {options.map((c) => {
          const on = c.key === value;
          return (
            <button key={c.key} type="button" className={on ? `${styles.o} ${styles.on}` : styles.o} role="radio" aria-checked={on} onClick={() => onChange(c.key)}>
              <span className={styles.cn}>{c.label}</span>
              <span className={styles.cd}>{c.sub}</span>
            </button>
          );
        })}
      </div>
    </>
  );
}

/** Labelled synthetic-demo control row (prototype `.btn.demo`). */
export function DemoControls({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className={styles.demoRow} role="group" aria-label={label}>
      <span className={styles.meta}>{label}</span>
      {children}
    </div>
  );
}
