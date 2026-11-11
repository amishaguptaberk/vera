'use client';

import { useEffect, useRef, type CSSProperties, type ReactNode, type RefObject } from 'react';
import styles from './Drawer.module.css';
import { useMediaQuery } from './useMediaQuery';

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])';

export type DrawerProps = {
  open: boolean;
  onClose: () => void;
  side?: 'left' | 'right';
  /** Accessible name of the panel (an `aside` landmark). */
  label: string;
  /** Accessible name of the scrim's close button. */
  closeLabel: string;
  /**
   * `always`: a drawer at every width. `narrow`: an ordinary element above 760px and an off-canvas drawer
   * (with scrim, focus trap and Escape) at 760px and below.
   */
  mode?: 'always' | 'narrow';
  /** Element focus returns to on close (e.g. the top-bar menu button). Falls back to the element focused at open. */
  returnFocusRef?: RefObject<HTMLElement | null>;
  className?: string;
  style?: CSSProperties;
  width?: string;
  children: ReactNode;
  /** Reference to the panel element, for owners that update its style directly (splitter drag). */
  panelRef?: RefObject<HTMLElement | null>;
  /** Hook for the parity suite (tests/parity/states.ts selects regions by it). */
  'data-parity'?: string;
};

export function Drawer({
  open,
  onClose,
  side = 'left',
  label,
  closeLabel,
  mode = 'always',
  returnFocusRef,
  className,
  style,
  width,
  children,
  panelRef,
  'data-parity': dataParity,
}: DrawerProps) {
  const narrow = useMediaQuery('(max-width: 760px)');
  const modal = mode === 'always' || narrow;
  const own = useRef<HTMLElement | null>(null);
  const ref = panelRef ?? own;
  const active = modal && open;

  // Focus: move into the drawer on open, trap Tab, close on Escape, return focus on close.
  useEffect(() => {
    if (!active) return;
    const panel = ref.current;
    if (!panel) return;
    const opener = (returnFocusRef?.current ?? document.activeElement) as HTMLElement | null;
    const items = () => Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
    (items()[0] ?? panel).focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'Tab') {
        const list = items();
        if (list.length === 0) return;
        const first = list[0];
        const last = list[list.length - 1];
        const cur = document.activeElement;
        if (!panel.contains(cur)) {
          e.preventDefault();
          first.focus();
        } else if (e.shiftKey && cur === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && cur === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      opener?.focus({ preventScroll: true });
    };
    // onClose identity may change every render; the trap must not re-run (it would steal focus).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const classes = [styles.panel, styles[side], styles[mode], open ? styles.open : '', className].filter(Boolean);
  return (
    <>
      <aside
        ref={ref as RefObject<HTMLElement>}
        aria-label={label}
        role={active ? 'dialog' : undefined}
        aria-modal={active ? true : undefined}
        // Off-canvas and closed: keep it out of the tab order and the accessibility tree.
        inert={modal && !open ? true : undefined}
        tabIndex={-1}
        data-parity={dataParity}
        className={classes.join(' ')}
        style={width ? ({ ...style, '--drawer-width': width } as CSSProperties) : style}
      >
        {children}
      </aside>
      {active ? <button type="button" className={styles.scrim} aria-label={closeLabel} onClick={onClose} /> : null}
    </>
  );
}
