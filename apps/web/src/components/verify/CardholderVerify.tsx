import { Button } from '@/design-system/primitives';
import styles from './Verify.module.css';

export type CardholderVerifyProps = {
  heading: string;
  /** Charge header lines (from the case view). */
  meta: readonly string[];
  channel: 'otp' | 'push';
  /** Supporting copy under the question. */
  text: string;
  /**
   * Synthetic demo only: the simulated text message, fetched from the cardholder-only outbox route.
   * Rendered ONLY in this cardholder-role control, inside the labelled demo box.
   */
  demo?: { label: string; code: string | null } | null;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onApprove: () => void;
  onDeny: () => void;
  /** "Expires in 9 minutes · 2 attempts left" */
  expiry?: string;
  message?: string | null;
  busy?: boolean;
  /** Terminal state copy (verified / not completed). */
  done?: { title: string; text: string } | null;
};

/** Cardholder view → "Verify it's you" task card (prototype `ch.hasIdv`). */
export function CardholderVerify(p: CardholderVerifyProps) {
  return (
    <div className={styles.ctask}>
      <div className={styles.card}>
        <div className={styles.ch}>
          <h2>{p.heading}</h2>
          {p.meta.map((m) => (
            <div key={m} className={styles.cm}>
              {m}
            </div>
          ))}
        </div>
        {p.done ? (
          <div className={styles.done} role="status">
            <strong>{p.done.title}</strong>
            <p>{p.done.text}</p>
          </div>
        ) : (
          <div className={styles.cb} aria-live="polite">
            <div>
              <div className={styles.ck}>Verify it’s you</div>
              <p className={styles.cq}>{p.channel === 'push' ? 'Did you ask Finance to verify you?' : 'Enter the code sent to your phone'}</p>
              <p className={`${styles.rd} ${styles.ctext}`}>{p.text}</p>
            </div>
            {p.channel === 'otp' ? (
              <>
                {p.demo ? (
                  <div className={styles.demoBox} data-testid="cardholder-demo-outbox">
                    <div className={styles.dt}>{p.demo.label}</div>
                    {p.demo.code ? (
                      <p className={styles.dp}>
                        Ramp: <b className={styles.tnum}>{p.demo.code}</b> is your verification code for a Finance review of your card. Ramp Finance will never ask you for it.
                      </p>
                    ) : (
                      <p className={styles.dp}>No active message.</p>
                    )}
                  </div>
                ) : null}
                <div className={styles.field}>
                  <label htmlFor="chotp">6-digit code</label>
                  <input
                    id="chotp"
                    className={styles.otp}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    value={p.value}
                    onChange={(e) => p.onChange(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        p.onSubmit();
                      }
                    }}
                  />
                </div>
                {p.message ? (
                  <p className={styles.msg} role="status" style={{ margin: 0 }}>
                    {p.message}
                  </p>
                ) : null}
                <div className={styles.cf}>
                  <Button variant="go" onClick={p.onSubmit} disabled={p.busy}>
                    Verify
                  </Button>
                  <span className={styles.rd}>{p.expiry}</span>
                </div>
              </>
            ) : (
              <>
                {p.message ? (
                  <p className={styles.msg} role="status" style={{ margin: 0 }}>
                    {p.message}
                  </p>
                ) : null}
                <div className={styles.cf}>
                  <Button variant="go" onClick={p.onApprove} disabled={p.busy}>
                    Approve
                  </Button>
                  <Button onClick={p.onDeny} disabled={p.busy}>
                    Deny
                  </Button>
                  <span className={styles.rd}>{p.expiry}</span>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
