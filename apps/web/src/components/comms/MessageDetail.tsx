'use client';

import type { ReactNode } from 'react';
import { Button } from '@/design-system/primitives';
import styles from './Comms.module.css';
import type { KV, MessageResponse } from './types';

export type MessageDetailProps = {
  kind: string;
  id: string;
  kv: readonly KV[];
  origLabel: string;
  body: string;
  response: MessageResponse | null;
  questions: readonly string[];
  /** Draft editor (drafted) or the actions row (sent). */
  children?: ReactNode;
  links?: readonly { label: string; go: () => void }[];
  onBack: () => void;
};

/** Prototype message detail (Main.dc.html:1745-1760). */
export function MessageDetail(p: MessageDetailProps) {
  return (
    <div>
      <Button variant={['sm', 'ghost']} className={styles.back} onClick={p.onBack}>
        ← All communications
      </Button>
      <div className={styles.h}>
        <span className={styles.ht}>{p.kind}</span>
        <span className={styles.id}>{p.id}</span>
      </div>
      <dl className={styles.kv}>
        {p.kv.map((r) => (
          <Row key={r.k} {...r} />
        ))}
      </dl>
      <details className={styles.orig}>
        <summary>{p.origLabel} · show full message</summary>
        <div className={styles.body}>{p.body}</div>
      </details>
      {p.response ? (
        <div className={styles.resp}>
          <div className={styles.rh}>
            <span className={styles.ht}>Response</span>
            <span className={styles.meta}>{p.response.meta}</span>
            {p.response.isNew ? <span className={styles.new}>New</span> : null}
          </div>
          <blockquote className={styles.q}>“{p.response.text}”</blockquote>
          <dl className={styles.kv}>
            {p.response.kv.map((r) => (
              <Row key={r.k} {...r} />
            ))}
          </dl>
          {p.questions.length ? (
            <>
              <div className={styles.sub}>Open questions</div>
              <ul className={styles.plain}>
                {p.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
      {p.children}
      {p.links?.length ? (
        <div className={styles.x}>
          {p.links.map((l) => (
            <button key={l.label} type="button" className={styles.linkb} onClick={l.go}>
              {l.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Row({ k, v }: KV) {
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}
