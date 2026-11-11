'use client';

import { cloneElement, useEffect, useId, useRef, useState, type ReactElement } from 'react';
import { createPortal } from 'react-dom';
import styles from './Tooltip.module.css';

export type TooltipProps = {
  label: string;
  side?: 'right' | 'top';
  /** The trigger: a single element that accepts `aria-describedby` (a button or link). */
  children: ReactElement<{ 'aria-describedby'?: string }>;
  /** Render nothing but the child (e.g. the label is already visible). */
  disabled?: boolean;
};

type Pos = { x: number; y: number };

/** Shows on hover and keyboard focus, hides on leave, blur and Escape. The tip is `role="tooltip"` and wired by aria-describedby. */
export function Tooltip({ label, side = 'right', children, disabled = false }: TooltipProps) {
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<Pos | null>(null);

  const show = () => {
    const el = wrap.current?.firstElementChild;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos(side === 'right' ? { x: r.right + 8, y: r.top + r.height / 2 } : { x: r.left + r.width / 2, y: r.top - 6 });
  };
  const hide = () => setPos(null);

  useEffect(() => {
    if (!pos) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setPos(null);
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [pos]);

  if (disabled) return children;
  return (
    // display:contents keeps the wrapper out of layout; the events bubble from the trigger.
    <span ref={wrap} style={{ display: 'contents' }} onMouseOver={show} onMouseOut={hide} onFocus={show} onBlur={hide}>
      {cloneElement(children, pos ? { 'aria-describedby': id } : {})}
      {pos
        ? createPortal(
            <span id={id} role="tooltip" className={side === 'top' ? `${styles.tip} ${styles.top}` : styles.tip} style={{ left: pos.x, top: pos.y }}>
              {label}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}
