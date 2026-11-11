'use client';

import Link from 'next/link';
import { useRef, type ReactElement, type RefObject } from 'react';
import { SIDEBAR_MAX, SIDEBAR_MIN } from '@/design-system/layout';
import { Drawer, Splitter, Tooltip, useMediaQuery } from '@/design-system/primitives';
import styles from './Sidebar.module.css';

export { SIDEBAR_MAX, SIDEBAR_MIN };

export type SidebarProps = {
  /** Current pathname: the active item derives from it. */
  pathname: string;
  /** Expanded width in px (220-320). */
  width: number;
  collapsed: boolean;
  /** Mobile (<=760px) off-canvas drawer state. */
  drawerOpen: boolean;
  /** The top-bar menu button: focus returns here when the drawer closes. */
  returnFocusRef?: RefObject<HTMLElement | null>;
  onWidthChange: (width: number) => void;
  onToggleCollapsed: () => void;
  onCloseDrawer: () => void;
};

// Routes: /cases, /automations/...
export const CASES_HREF = '/cases';
export const AUTOMATIONS_HREF = '/automations/workflows';
const SUB_ITEMS = [
  { label: 'Workflows', href: '/automations/workflows' },
  { label: 'Specialists', href: '/automations/specialists' },
  { label: 'Policies', href: '/automations/policies' },
] as const;

const under = (pathname: string, base: string) => pathname === base || pathname.startsWith(`${base}/`);

export function Sidebar({ pathname, width, collapsed, drawerOpen, returnFocusRef, onWidthChange, onToggleCollapsed, onCloseDrawer }: SidebarProps) {
  const panel = useRef<HTMLElement | null>(null);
  // The app root is the queue's landing route (the prototype's default screen is Cases), so it activates Cases too.
  const onCases = pathname === '/' || under(pathname, '/cases');
  const inAutomations = under(pathname, '/automations');
  // At <=760px the sidebar is the modal drawer: "Collapse" closes it and never touches the stored desktop collapse.
  const narrow = useMediaQuery('(max-width: 760px)');
  const shownCollapsed = collapsed && !narrow;
  const canResize = !collapsed;
  const tip = (label: string, el: ReactElement<{ 'aria-describedby'?: string }>) => (
    <Tooltip label={label} disabled={!shownCollapsed}>
      {el}
    </Tooltip>
  );

  return (
    <Drawer
      mode="narrow"
      side="left"
      open={drawerOpen}
      onClose={onCloseDrawer}
      label="Product navigation"
      closeLabel="Close navigation"
      returnFocusRef={returnFocusRef}
      panelRef={panel}
      data-parity="side"
      className={`${styles.side}${collapsed ? ` ${styles.col}` : ''}`}
      style={collapsed ? undefined : { flexBasis: width }}
    >
      <div className={styles.brand}>
        {/* eslint-disable-next-line @next/next/no-img-element -- a plain <img> keeps the prototype's intrinsic sizing */}
        <img src="/vera-logo.png" alt="Vera" />
      </div>
      <nav className={styles.nav} aria-label="Sections">
        {tip(
          'Cases',
          <Link href={CASES_HREF} className={onCases ? `${styles.item} ${styles.on}` : styles.item} aria-current={onCases ? 'page' : undefined} aria-label="Cases" onClick={onCloseDrawer}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M2.5 4.5h11v8h-11z M2.5 7.5h3.5l1 1.5h2l1-1.5h3.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
            </svg>
            <span>Cases</span>
          </Link>,
        )}
        <div className={styles.divider} role="separator" />
        {tip(
          'Automations',
          <Link href={AUTOMATIONS_HREF} className={inAutomations ? `${styles.item} ${styles.open}` : styles.item} aria-expanded={inAutomations} aria-label="Automations" onClick={onCloseDrawer}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="4" cy="4" r="1.8" fill="none" stroke="currentColor" strokeWidth="1.3" />
              <circle cx="12" cy="12" r="1.8" fill="none" stroke="currentColor" strokeWidth="1.3" />
              <path d="M5.8 4h3.2a2 2 0 0 1 2 2v4.2" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
            <span>Automations</span>
          </Link>,
        )}
        {inAutomations && !shownCollapsed ? (
          <div className={styles.sub}>
            {SUB_ITEMS.map((t) => {
              const on = under(pathname, t.href);
              return (
                <Link key={t.href} href={t.href} className={on ? styles.subOn : undefined} aria-current={on ? 'page' : undefined} onClick={onCloseDrawer}>
                  {t.label}
                </Link>
              );
            })}
          </div>
        ) : null}
      </nav>
      {tip(
        shownCollapsed ? 'Expand navigation' : 'Collapse navigation',
        <button type="button" className={styles.collapse} onClick={narrow ? onCloseDrawer : onToggleCollapsed} aria-label={shownCollapsed ? 'Expand navigation' : 'Collapse navigation'} title={shownCollapsed ? undefined : 'Collapse navigation'}>
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path d={shownCollapsed ? 'M6 3.5l4.5 4.5L6 12.5' : 'M10 3.5L5.5 8l4.5 4.5'} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>{shownCollapsed ? '' : 'Collapse'}</span>
        </button>,
      )}
      {canResize ? (
        <Splitter
          className={styles.split}
          label="Resize navigation"
          orientation="vertical"
          min={SIDEBAR_MIN}
          max={SIDEBAR_MAX}
          value={width}
          onChange={onWidthChange}
          onDragPreview={(w) => {
            if (panel.current) panel.current.style.flexBasis = `${w}px`;
          }}
        />
      ) : null}
    </Drawer>
  );
}
