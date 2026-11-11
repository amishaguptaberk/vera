'use client';

import { useState, type KeyboardEvent, type PointerEvent } from 'react';
import styles from './Splitter.module.css';

export type SplitterProps = {
  /** Accessible name, e.g. "Resize navigation". */
  label: string;
  orientation: 'vertical' | 'horizontal';
  min: number;
  max: number;
  value: number;
  /** Keyboard step and committed drag value. */
  onChange: (value: number) => void;
  /** Called on every pointer move while dragging so the owner can update the DOM directly; `onChange` follows once on release. */
  onDragPreview?: (value: number) => void;
  /** Arrow step (default 16) and Shift+Arrow step (default 64). */
  step?: number;
  bigStep?: number;
  /** Flip the drag/arrow direction (a panel resized from its left edge). */
  invert?: boolean;
  className?: string;
};

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

/**
 * Separator with this keyboard contract: arrows +/-16, Shift+arrows +/-64, Home = min, End = max.
 * Vertical separators resize with Left/Right, horizontal ones with Up/Down.
 */
export function Splitter({
  label,
  orientation,
  min,
  max,
  value,
  onChange,
  onDragPreview,
  step = 16,
  bigStep = 64,
  invert = false,
  className,
}: SplitterProps) {
  const [dragging, setDragging] = useState(false);
  const vertical = orientation === 'vertical';

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const inc = vertical ? 'ArrowRight' : 'ArrowUp';
    const dec = vertical ? 'ArrowLeft' : 'ArrowDown';
    const delta = e.shiftKey ? bigStep : step;
    const sign = invert ? -1 : 1;
    let next: number;
    if (e.key === inc) next = value + sign * delta;
    else if (e.key === dec) next = value - sign * delta;
    else if (e.key === 'Home') next = min;
    else if (e.key === 'End') next = max;
    else return;
    e.preventDefault();
    onChange(clamp(next, min, max));
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const start = vertical ? e.clientX : e.clientY;
    const startValue = value;
    const sign = (invert ? -1 : 1) * (vertical ? 1 : -1);
    let current = startValue;
    const cls = vertical ? 'vera-drag-col' : 'vera-drag-row';
    document.body.classList.add('vera-dragging', cls);
    setDragging(true);
    const move = (ev: globalThis.PointerEvent) => {
      const pos = vertical ? ev.clientX : ev.clientY;
      current = clamp(startValue + sign * (pos - start), min, max);
      onDragPreview?.(current);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      document.body.classList.remove('vera-dragging', cls);
      setDragging(false);
      onChange(current);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const classes = [styles.split, vertical ? '' : styles.horizontal, dragging ? styles.dragging : '', className].filter(Boolean);
  return (
    <div
      role="separator"
      aria-label={label}
      aria-orientation={orientation}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
      tabIndex={0}
      className={classes.join(' ')}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
    />
  );
}
