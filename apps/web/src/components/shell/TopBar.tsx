'use client';

import type { RefObject } from 'react';
import { Button, EnvironmentPill } from '@/design-system/primitives';
import { VeraButton } from '@/components/decision/VeraRail';
import { RoleSelector, type RoleSelectorProps } from './RoleSelector';
import styles from './TopBar.module.css';

export type TopBarProps = {
  /** Context title (prototype `ctxTitle`); may be empty. */
  title: string;
  /** With a sidebar the brand lives there and the menu button opens it on mobile; without one the brand is in the bar. */
  hasSidebar: boolean;
  navOpen: boolean;
  menuButtonRef?: RefObject<HTMLButtonElement | null>;
  onToggleNav: () => void;
  /** The one and only place the environment is shown (Handoff D6). */
  synthetic: boolean;
  role: RoleSelectorProps;
  /** Demo reset; the control is not rendered when absent. */
  onReset?: () => void;
  resetPending?: boolean;
  /** The Vera rail toggle (prototype `.vera-b`, visible below 1280px) when the page has a rail. */
  rail?: { open: boolean; onToggle: () => void } | null;
};

export function TopBar({ title, hasSidebar, navOpen, menuButtonRef, onToggleNav, synthetic, role, onReset, resetPending = false, rail = null }: TopBarProps) {
  return (
    <header className={styles.top} data-parity="top">
      <div className={styles.bar}>
        {hasSidebar ? (
          <button ref={menuButtonRef} type="button" className={styles.menu} aria-label="Open navigation" aria-expanded={navOpen} onClick={onToggleNav}>
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
              <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        ) : (
          <div className={styles.brand}>
            {/* eslint-disable-next-line @next/next/no-img-element -- a plain <img> keeps the prototype's intrinsic sizing */}
            <img src="/vera-logo.png" alt="Vera" />
          </div>
        )}
        <h1 className={styles.title}>{title}</h1>
        <div className={styles.controls}>
          {rail ? <VeraButton open={rail.open} onToggle={rail.onToggle} /> : null}
          {synthetic ? <EnvironmentPill /> : null}
          <RoleSelector {...role} />
          {onReset ? (
            <Button variant={['sm', 'ghost']} onClick={onReset} disabled={resetPending}>
              Reset
            </Button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
