import styles from './StatusSlot.module.css';

export const SLOT_STATES = ['idle', 'review', 'wait', 'block', 'done', 'work'] as const;
export type SlotState = (typeof SLOT_STATES)[number];

export type StatusSlotProps = {
  state: SlotState;
  /** Accessible name. The slot is decorative (aria-hidden) when omitted: the adjacent text carries the status. */
  label?: string;
};

/** Fixed 20x20 status slot. All six marks are always mounted; the active one fades in (no layout shift). */
export function StatusSlot({ state, label }: StatusSlotProps) {
  return (
    <span
      className={styles.slot}
      data-state={state}
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
    >
      {SLOT_STATES.map((s) => (
        <span key={s} className={`${styles.mark} ${styles[s]}${s === state ? ` ${styles.on}` : ''}`} />
      ))}
    </span>
  );
}
