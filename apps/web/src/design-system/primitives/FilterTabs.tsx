import styles from './FilterTabs.module.css';

export type FilterItem = { id: string; label: string; count?: number };

export type FilterTabsProps = {
  items: readonly FilterItem[];
  value: string;
  onChange: (id: string) => void;
  label: string;
};

export function FilterTabs({ items, value, onChange, label }: FilterTabsProps) {
  return (
    <div className={styles.filt} role="group" aria-label={label}>
      {items.map((f) => (
        <button
          key={f.id}
          type="button"
          aria-pressed={f.id === value}
          className={f.id === value ? `${styles.fb} ${styles.on}` : styles.fb}
          onClick={() => onChange(f.id)}
        >
          {f.label}
          {f.count !== undefined ? <span className={styles.count}>{f.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
