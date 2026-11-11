import { RefChip } from '@/design-system/primitives';
import styles from './Money.module.css';

export type ControlItem = {
  key: string;
  label: string;
  why: string;
  affects: string;
  effect: string;
  reversible: string;
  permission: string;
  record_id?: string | null;
};

export type ControlPlanProps = {
  items: readonly ControlItem[];
  selected: ReadonlySet<string>;
  /** Selection is editable only while the server offers a command that takes a control list. */
  editable: boolean;
  onToggle: (key: string) => void;
  onOpenRecord?: (id: string) => void;
};

/** Prototype "Recommended controls for this case" (.ctl rows). Buttons are rendered by the action bar, not here. */
export function ControlPlan({ items, selected, editable, onToggle, onOpenRecord }: ControlPlanProps) {
  if (!items.length) return null;
  return (
    <div data-testid="control-plan">
      <div className={styles.rl}>Recommended controls for this case</div>
      {items.map((c) => (
        <div key={c.key} className={styles.ctl}>
          <input type="checkbox" checked={selected.has(c.key)} onChange={() => onToggle(c.key)} disabled={!editable} aria-label={c.label} />
          <div className={styles.ctlBody}>
            <div className={styles.ctlLabel}>{c.label}</div>
            <div className={styles.cd}>{c.why}</div>
            <div className={styles.cd}>
              Affects {c.affects} · {c.effect} · Reversible: {c.reversible} · Permission: {c.permission}
            </div>
          </div>
          {c.record_id && onOpenRecord ? (
            <span data-ref>
              <RefChip onClick={() => onOpenRecord(c.record_id!)}>{c.record_id}</RefChip>
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}
