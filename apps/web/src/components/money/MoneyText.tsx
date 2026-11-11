import styles from './Money.module.css';

/** Prototype `.f-p` paragraphs. */
export function TaskParas({ paras }: { paras: readonly string[] }) {
  return (
    <>
      {paras.map((p) => (
        <p key={p} className={styles.fP}>
          {p}
        </p>
      ))}
    </>
  );
}

/** Decision D6: "Simulated · No funds moved" marks money and control actions only. */
export function SimulatedNote() {
  return (
    <span className={styles.simnote} data-testid="money-sim">
      Simulated · No funds moved
    </span>
  );
}

export function TaskNote({ text }: { text: string }) {
  return <div className={styles.fNote}>{text}</div>;
}
