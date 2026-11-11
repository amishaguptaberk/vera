'use client';

import { useEffect, useRef, type KeyboardEvent } from 'react';
import styles from './Menu.module.css';

export type MenuItem = { id: string; label: string; description?: string; checked?: boolean; disabled?: boolean };

export type MenuProps = {
  label: string;
  items: readonly MenuItem[];
  onSelect: (id: string) => void;
  /** Escape or a click outside the menu. The owner restores focus to its trigger. */
  onClose: () => void;
};

/** `role="menu"` of `menuitemradio` items. Arrows/Home/End move focus; Enter and Space select; Escape closes. */
export function Menu({ label, items, onSelect, onClose }: MenuProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const checked = items.findIndex((i) => i.checked && !i.disabled);
    const first = items.findIndex((i) => !i.disabled);
    refs.current[checked >= 0 ? checked : first]?.focus();
    // Focus once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const move = (from: number, dir: 1 | -1) => {
    for (let n = 1; n <= items.length; n++) {
      const i = (from + dir * n + items.length * n) % items.length;
      if (!items[i].disabled) return refs.current[i]?.focus();
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const from = refs.current.findIndex((el) => el === document.activeElement);
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      move(from, 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      move(from, -1);
    } else if (e.key === 'Home') {
      e.preventDefault();
      refs.current[items.findIndex((i) => !i.disabled)]?.focus();
    } else if (e.key === 'End') {
      e.preventDefault();
      const last = items.map((i) => !i.disabled).lastIndexOf(true);
      refs.current[last]?.focus();
    } else if (e.key === 'Tab') {
      onClose();
    }
  };

  return (
    <>
      <button type="button" className={styles.scrim} tabIndex={-1} aria-hidden="true" onClick={onClose} />
      <div className={styles.menu} role="menu" aria-label={label} onKeyDown={onKeyDown}>
        {items.map((item, i) => (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="menuitemradio"
            aria-checked={!!item.checked}
            disabled={item.disabled}
            tabIndex={-1}
            className={item.checked ? `${styles.item} ${styles.checked}` : styles.item}
            onClick={() => onSelect(item.id)}
          >
            <span className={styles.name}>{item.label}</span>
            {item.description ? <span className={styles.desc}>{item.description}</span> : null}
          </button>
        ))}
      </div>
    </>
  );
}
