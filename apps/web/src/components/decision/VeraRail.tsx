import { useEffect, useRef, type KeyboardEvent } from 'react';
import { RefChip } from '@/design-system/primitives';
import styles from './VeraRail.module.css';

export type RailCite = { record_id: string; label: string };
export type RailButton = { key: string; label: string; enabled?: boolean };
export type RailWorkLine = { text: string; ref?: string | null };
export type RailMessage =
  | { kind: 'user'; id: string; text: string }
  | { kind: 'sys'; id: string; text: string; at?: string }
  | { kind: 'vera'; id: string; who: string; at?: string; title?: string | null; paras: readonly string[]; cites: readonly RailCite[]; actions?: readonly RailButton[] }
  | { kind: 'work'; id: string; who: string; at?: string; head: string; running: boolean; lines: readonly RailWorkLine[] };

export type VeraRailProps = {
  open: boolean;
  sub?: string | null;
  messages: readonly RailMessage[];
  emptyText?: string;
  chips: readonly string[];
  input: string;
  placeholder: string;
  sending: boolean;
  selected?: string | null;
  onInput: (v: string) => void;
  onAsk: (text: string) => void;
  onClose: () => void;
  onSelectRecord: (recordId: string) => void;
  onAction?: (key: string) => void;
};

const Close = () => (
  <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
    <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

/** The Vera rail (prototype aside#vera-rail). Below 1280px it is a right drawer opened by `VeraButton`. */
export function VeraRail(p: VeraRailProps) {
  const msgsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = msgsRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [p.messages.length]);
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (p.input.trim() && !p.sending) p.onAsk(p.input);
    }
  };
  return (
    <>
      {p.open ? <button type="button" className={styles.scrim} aria-label="Close Vera" onClick={p.onClose} /> : null}
      <aside className={p.open ? `${styles.rail} ${styles.open}` : styles.rail} id="vera-rail" aria-label="Conversation with Vera">
        <div className={styles.railH} data-parity="rail-head">
          {/* eslint-disable-next-line @next/next/no-img-element -- fixed 22px mark, as in the prototype */}
          <img className={styles.logo} src="/vera-mark.png" alt="" />
          <div>
            <div className={styles.railT}>Vera</div>
            {p.sub ? <div className={styles.railS}>{p.sub}</div> : null}
          </div>
          <button type="button" className={styles.railX} aria-label="Close Vera" onClick={p.onClose}>
            <Close />
          </button>
        </div>
        <div className={styles.msgs} ref={msgsRef} aria-live="polite">
          {!p.messages.length && p.emptyText ? <div className={styles.empty}>{p.emptyText}</div> : null}
          {p.messages.map((m) => {
            if (m.kind === 'user')
              return (
                <div key={m.id} className={styles.user}>
                  <div className={styles.bub}>{m.text}</div>
                </div>
              );
            if (m.kind === 'sys')
              return (
                <div key={m.id} className={styles.sys}>
                  <span>{m.text}</span>
                  {m.at ? <span className={styles.t}>{m.at}</span> : null}
                </div>
              );
            return (
              <div key={m.id} className={styles.vera} data-kind={m.kind}>
                <div className={styles.meta}>
                  <span>{m.at ? `${m.who} · ${m.at}` : m.who}</span>
                </div>
                {m.kind === 'work' ? (
                  <div>
                    <div className={m.running ? `${styles.mwH} ${styles.run}` : styles.mwH}>
                      <span>{m.head}</span>
                    </div>
                    {m.lines.length ? (
                      <ul className={styles.mwL}>
                        {m.lines.map((ln, i) => (
                          <li key={i}>
                            <span>{ln.text}</span>
                            {ln.ref ? (
                              <RefChip on={p.selected === ln.ref} onClick={() => p.onSelectRecord(ln.ref!)}>
                                {ln.ref}
                              </RefChip>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : (
                  <>
                    {m.title ? <div className={styles.mTitle}>{m.title}</div> : null}
                    {m.paras.map((t, i) => (
                      <p key={i} className={styles.mP}>
                        {t}
                      </p>
                    ))}
                    {m.cites.length ? (
                      <div className={styles.cites}>
                        {m.cites.map((c) => (
                          <RefChip key={c.label} on={p.selected === c.record_id} onClick={() => p.onSelectRecord(c.record_id)}>
                            {c.label}
                          </RefChip>
                        ))}
                      </div>
                    ) : null}
                    {m.actions?.length ? (
                      <div className={styles.act}>
                        {m.actions.map((a) => (
                          <button key={a.key} type="button" className={styles.chip} disabled={a.enabled === false} onClick={() => p.onAction?.(a.key)}>
                            {a.label}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            );
          })}
        </div>
        <div className={styles.composer}>
          {p.chips.length && !p.sending ? (
            <div className={styles.chips}>
              {p.chips.map((t) => (
                <button key={t} type="button" className={styles.chip} onClick={() => p.onAsk(t)}>
                  {t}
                </button>
              ))}
            </div>
          ) : null}
          <div className={styles.compBox}>
            <label className={styles.sr} htmlFor="askin">
              Message Vera
            </label>
            <input
              id="askin"
              className={styles.compIn}
              value={p.input}
              onChange={(e) => p.onInput(e.target.value)}
              onKeyDown={onKey}
              placeholder={p.placeholder}
              disabled={p.sending}
            />
            <button type="button" className={styles.send} onClick={() => p.onAsk(p.input)} disabled={!p.input.trim() || p.sending} aria-label="Send">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <path d="M7 12V2M2.5 6.5L7 2l4.5 4.5" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

/** Header toggle `.vera-b` (visible below 1280px only, via CSS). */
export function VeraButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button type="button" className={styles.veraB} aria-controls="vera-rail" aria-expanded={open} onClick={onToggle}>
      Vera
    </button>
  );
}
