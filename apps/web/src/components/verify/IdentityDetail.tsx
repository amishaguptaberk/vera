import type { ReactNode } from "react";
import { Button, RefChip } from "@/design-system/primitives";
import styles from "./Verify.module.css";

export type KV = { k: string; v: string };

export type IdentityDetailProps = {
  /** Rows of the request (channel, bound to, sent, attempts, status). Never a code: the analyst view has no code. */
  rows: readonly KV[];
  history: readonly string[];
  /** One-line structured result ("Priya controls the approved channel." / "Identity not verified."). */
  result: string;
  resultRows: readonly KV[];
  sources: readonly string[];
  onOpenSource?: (id: string) => void;
  /** Resend cooldown countdown, e.g. "Resend available in 42s". */
  cooldown?: string | null;
  /** Inline message (blocked reason, cancelled note). */
  message?: string | null;
  /** Server-offered actions (rendered by the caller with ActionBar). */
  actions?: ReactNode;
  onBack?: () => void;
};

/** Communications → identity verification detail (prototype `cm.isCall` with `it.kind === 'idv'`). */
export function IdentityDetail({
  rows,
  history,
  result,
  resultRows,
  sources,
  onOpenSource,
  cooldown,
  message,
  actions,
  onBack,
}: IdentityDetailProps) {
  return (
    <div data-testid="identity-detail">
      {onBack ? (
        <Button
          variant={["sm", "ghost"]}
          className={styles.back}
          onClick={onBack}
        >
          ← All communications
        </Button>
      ) : null}
      <div className={styles.h}>
        <span className={styles.ht}>Identity verification</span>
        <span className={styles.id}>One-time code</span>
      </div>
      <dl className={styles.kvl}>
        {rows.map((r) => (
          <KVRow key={r.k} {...r} />
        ))}
      </dl>
      <div className={styles.sub}>History</div>
      <ol className={styles.ql}>
        {history.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ol>
      <div className={styles.res}>
        <div className={styles.sub}>Structured result</div>
        <p className={styles.rt}>{result}</p>
        <dl className={styles.kvl}>
          {resultRows.map((r) => (
            <KVRow key={r.k} {...r} />
          ))}
        </dl>
      </div>
      {sources.length ? (
        <div className={styles.src}>
          <span>Sources</span>
          {sources.map((id) => (
            <RefChip
              key={id}
              onClick={onOpenSource ? () => onOpenSource(id) : undefined}
            >
              {id}
            </RefChip>
          ))}
        </div>
      ) : null}
      {message ? (
        <p className={styles.msg} role="status">
          {message}
        </p>
      ) : null}
      {cooldown ? (
        <p className={styles.rd} aria-live="polite">
          {cooldown}
        </p>
      ) : null}
      {actions}
    </div>
  );
}

export function KVRow({ k, v }: KV) {
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}
