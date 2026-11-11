import { RefChip } from '@/design-system/primitives';
import styles from './Decision.module.css';

export type PacketSectionProps = { key: string; label: string; value: string; record_ids?: readonly string[] | null };
export type PacketRule = { label: string; passed: boolean; record_ids?: readonly string[] | null };

export type PacketViewProps = {
  sections: readonly PacketSectionProps[];
  refs?: readonly string[];
  policy?: { label: string; rules?: readonly PacketRule[] | null; evidence?: readonly string[] | null } | null;
  versions?: string | null;
  selected?: string | null;
  onSelectRecord?: (recordId: string) => void;
};

/** Decision packet read view (prototype `rv.sections` .pk rows, `.m-cites` refs, "Prepared by Vera" fine print). */
export function PacketView({ sections, refs = [], policy, versions, selected, onSelectRecord }: PacketViewProps) {
  const chip = (id: string) => (
    <RefChip key={id} on={selected === id} onClick={() => onSelectRecord?.(id)}>
      {id}
    </RefChip>
  );
  return (
    <div data-testid="packet">
      {sections.map((s) => (
        <div key={s.key} className={styles.pk}>
          {s.label ? <div className={styles.pkK}>{s.label}</div> : null}
          <div>{s.value}</div>
          {s.record_ids?.length ? <div className={styles.cites}>{s.record_ids.map(chip)}</div> : null}
        </div>
      ))}
      {policy ? (
        <div className={styles.pk}>
          <div className={styles.pkK}>Policy</div>
          <div>{policy.label}</div>
          {policy.rules?.length ? (
            <ul className={styles.rules}>
              {policy.rules.map((r) => (
                <li key={r.label} className={styles.ruleRow}>
                  <span className={r.passed ? undefined : styles.fail}>{r.label}</span>
                  {!r.passed ? (r.record_ids ?? []).map(chip) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {policy.evidence?.length ? <div className={styles.cites}>{policy.evidence.map(chip)}</div> : null}
        </div>
      ) : null}
      {versions ? (
        <div className={styles.pk}>
          <div className={styles.pkK}>Versions</div>
          <div>{versions}</div>
        </div>
      ) : null}
      {refs.length ? <div className={styles.cites}>{refs.map(chip)}</div> : null}
      <p className={styles.fine}>Prepared by Vera · check each point against its source record.</p>
    </div>
  );
}
