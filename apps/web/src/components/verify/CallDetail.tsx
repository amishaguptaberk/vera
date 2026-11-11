import type { ReactNode } from "react";
import { Button, RefChip } from "@/design-system/primitives";
import { KVRow, type KV } from "./IdentityDetail";
import styles from "./Verify.module.css";

export type TranscriptLine = {
  key: string | number;
  who: string;
  text: string;
  system?: boolean;
};

export type CallResultBlock = {
  /** Headline sentence of the structured result. */
  headline: string;
  /** Structured fields (outcome, authorization answer, answers). */
  rows: readonly KV[];
  /** Fact status / policy effect. */
  effect: readonly KV[];
};

export type CallNotes = {
  value: string;
  onChange: (v: string) => void;
  onSave: () => void;
  saved?: string;
  busy?: boolean;
  canSave: boolean;
};

export type CallDetailProps = {
  title: string;
  idLabel: string;
  live?: boolean;
  rows: readonly KV[];
  /** The call target, shown with its SOURCE record chip (e.g. PRF-4418 · phone). */
  target?: { text: string; recordId: string; field?: string } | null;
  questionsLabel: string;
  questions: readonly string[];
  /** null = no transcript section (proposed shows "Not started."). */
  transcript: readonly TranscriptLine[] | null;
  noTranscriptText?: string;
  result?: CallResultBlock | null;
  notes?: CallNotes | null;
  sources: readonly string[];
  onOpenSource?: (id: string) => void;
  actions?: ReactNode;
  onBack?: () => void;
};

/** Communications → verification call (prototype `cm.isCall`: proposed / in progress / complete / call failed). */
export function CallDetail(p: CallDetailProps) {
  const open = (id: string) =>
    p.onOpenSource ? () => p.onOpenSource!(id) : undefined;
  return (
    <div data-testid="call-detail">
      {p.onBack ? (
        <Button
          variant={["sm", "ghost"]}
          className={styles.back}
          onClick={p.onBack}
        >
          ← All communications
        </Button>
      ) : null}
      <div className={styles.h}>
        <span className={styles.ht}>{p.title}</span>
        <span className={styles.id}>{p.idLabel}</span>
        {p.live ? (
          <span className={styles.live}>
            <span className={styles.spin} aria-hidden="true" />
            Live
          </span>
        ) : null}
      </div>
      <dl className={styles.kvl}>
        {p.target ? (
          <>
            <dt>Target</dt>
            <dd>
              {p.target.text}{" "}
              <RefChip
                onClick={open(p.target.recordId)}
                aria-label={`Source record ${p.target.recordId}`}
              >
                {p.target.recordId}
                {p.target.field ? ` · ${p.target.field}` : ""}
              </RefChip>
            </dd>
          </>
        ) : null}
        {p.rows.map((r) => (
          <KVRow key={r.k} {...r} />
        ))}
      </dl>
      <div className={styles.sub}>{p.questionsLabel}</div>
      <ol className={styles.ql}>
        {p.questions.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ol>
      <div className={styles.sub}>Transcript</div>
      {p.transcript && p.transcript.length ? (
        <div className={styles.tr} aria-live="polite" data-testid="transcript">
          {p.transcript.map((l) => (
            <div
              key={l.key}
              className={[styles.tl, styles.tlNew, l.system ? styles.sys : ""]
                .filter(Boolean)
                .join(" ")}
            >
              <div className={styles.tw}>{l.who}</div>
              <div className={styles.tt}>{l.text}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className={styles.rd}>{p.noTranscriptText ?? "Not started."}</p>
      )}
      {p.result ? (
        <div className={styles.res} data-testid="structured-result">
          <div className={styles.sub}>Structured result</div>
          <p className={styles.rt}>{p.result.headline}</p>
          {p.result.rows.length ? (
            <dl className={styles.kvl}>
              {p.result.rows.map((r) => (
                <KVRow key={r.k} {...r} />
              ))}
            </dl>
          ) : null}
          <dl className={styles.kvl}>
            {p.result.effect.map((r) => (
              <KVRow key={r.k} {...r} />
            ))}
          </dl>
          {p.notes ? (
            <>
              <div className={styles.noteField}>
                <label htmlFor="cnote">Reviewer notes</label>
                <textarea
                  id="cnote"
                  className={styles.ta}
                  value={p.notes.value}
                  onChange={(e) => p.notes!.onChange(e.target.value)}
                  placeholder="Add context for the reviewer"
                />
              </div>
              <div className={styles.row}>
                <Button
                  variant="sm"
                  onClick={p.notes.onSave}
                  disabled={!p.notes.canSave || p.notes.busy}
                >
                  Save note
                </Button>
                <span className={styles.meta}>{p.notes.saved ?? ""}</span>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
      {p.sources.length ? (
        <div className={styles.src}>
          <span>Sources</span>
          {p.sources.map((id) => (
            <RefChip key={id} onClick={open(id)}>
              {id}
            </RefChip>
          ))}
        </div>
      ) : null}
      {p.actions}
    </div>
  );
}
