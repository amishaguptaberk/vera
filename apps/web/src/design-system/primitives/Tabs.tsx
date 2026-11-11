'use client';

import { useRef, type KeyboardEvent } from 'react';
import styles from './Tabs.module.css';

export type TabItem = { id: string; label: string };

export type TabsProps = {
  items: readonly TabItem[];
  value: string;
  onChange: (id: string) => void;
  label?: string;
  variant?: 'default' | 'sub' | 'drawer';
};

/** Text tabs: active = ink + 2px ink underline (Handoff §9.4). Arrow keys, Home and End move between tabs. */
export function Tabs({ items, value, onChange, label, variant = 'default' }: TabsProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (e: KeyboardEvent, index: number) => {
    let next = index;
    if (e.key === 'ArrowRight') next = (index + 1) % items.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = items.length - 1;
    else return;
    e.preventDefault();
    refs.current[next]?.focus();
    onChange(items[next].id);
  };
  const wrap = variant === 'default' ? styles.tabs : `${styles.tabs} ${styles[variant]}`;
  return (
    <div className={wrap} role="tablist" aria-label={label}>
      {items.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="tab"
          aria-selected={t.id === value}
          tabIndex={t.id === value ? 0 : -1}
          className={t.id === value ? `${styles.tab} ${styles.active}` : styles.tab}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
