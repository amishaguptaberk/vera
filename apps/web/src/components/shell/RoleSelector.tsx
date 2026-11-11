'use client';

import { useRef, useState } from 'react';
import { Menu, Skeleton } from '@/design-system/primitives';
import styles from './RoleSelector.module.css';

export type RoleViewId = 'analyst' | 'cardholder' | 'reviewer';

export type RoleOption = { id: RoleViewId; label: string; shortLabel: string; description: string };

// Prototype copy (Main.dc.html:2867-2869). The reviewer description is the prototype's demo text, verbatim.
export const ROLE_OPTIONS: readonly RoleOption[] = [
  { id: 'analyst', label: 'Finance analyst', shortLabel: 'Finance analyst', description: 'Investigates and prepares decisions' },
  { id: 'cardholder', label: 'Cardholder', shortLabel: 'Cardholder', description: 'Responds to finance questions' },
  {
    id: 'reviewer',
    label: 'Reviewer · card admin',
    shortLabel: 'Reviewer',
    description: 'Dana Okafor · two separate permissions: approves credit as reviewer, approves and applies card controls as card admin',
  },
];

export type RoleSelectorProps = {
  /** No session yet: a skeleton stands in for the control. There is no fallback role. */
  loading: boolean;
  selected: RoleViewId | null;
  /** A switch is in flight: the control is disabled so a second request cannot start. */
  pending?: boolean;
  onSelect: (role: RoleViewId) => void;
};

export function RoleSelector({ loading, selected, pending = false, onSelect }: RoleSelectorProps) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);

  if (loading || selected === null) {
    return (
      <div className={styles.rsel} aria-busy="true" data-testid="role-selector-loading">
        <Skeleton width={152} height={32} radius={7} />
      </div>
    );
  }

  const current = ROLE_OPTIONS.find((o) => o.id === selected) ?? ROLE_OPTIONS[0];
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };

  return (
    <div className={styles.rsel}>
      <button
        ref={trigger}
        type="button"
        className={styles.btn}
        aria-label={`Viewing as ${current.shortLabel}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={pending}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={styles.key}>Viewing as</span>
        <span className={styles.value}>{current.shortLabel}</span>
        <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">
          <path d="M2 3.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open ? (
        <Menu
          label="Demo role"
          items={ROLE_OPTIONS.map((o) => ({ id: o.id, label: o.label, description: o.description, checked: o.id === selected }))}
          onClose={close}
          onSelect={(id) => {
            close();
            if (id !== selected) onSelect(id as RoleViewId);
          }}
        />
      ) : null}
    </div>
  );
}
