import { useState, type ReactNode } from "react";
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
  /** Structured answers per question, each citing transcript line seqs. */
  answers?: readonly CallAnswerRow[];
};

export type CallAnswerRow = {
  question: string;
  answer: string;
  lines: readonly number[];
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
  /** Plain provider label, e.g. "Simulated call" / "Voice call via ElevenLabs". */
  provider?: string | null;
  /** Elapsed time while the call is pending or live. */
  elapsed?: string | null;
  /** Required consent checkbox (preparation / retry). */
  consent?: { checked: boolean; onChange: (v: boolean) => void } | null;
};

/** Communications → verification call (prototype `cm.isCall`: proposed / in progress / complete / call failed). */
export function CallDetail(p: CallDetailProps) {
  const open = (id: string) =>
    p.onOpenSource ? () => p.onOpenSource!(id) : undefined;
  const [hl, setHl] = useState<string | null>(null);
  const cite = (n: number) => () => {
    const key = String(n);
    setHl(key);
    const el = document.getElementById(`call-line-${key}`);
    if (el && typeof el.scrollIntoView === "function")
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
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
      {p.provider || p.elapsed ? (
        <p className={styles.meta} data-testid="call-provider">
          {p.provider ?? ""}
          {p.provider && p.elapsed ? " · " : ""}
          {p.elapsed ? `Elapsed ${p.elapsed}` : ""}
        </p>
      ) : null}
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
              id={`call-line-${l.key}`}
              data-line={l.key}
              aria-current={hl === String(l.key) ? "true" : undefined}
              className={[
                styles.tl,
                styles.tlNew,
                l.system ? styles.sys : "",
                hl === String(l.key) ? styles.tlHl : "",
              ]
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
          {p.result.answers?.length ? (
            <ol className={styles.ql} data-testid="call-answers">
              {p.result.answers.map((a, i) => (
                <li key={i}>
                  <div>{a.question}</div>
                  <div>
                    <strong>{a.answer}</strong>{" "}
                    {a.lines.map((n) => (
                      <RefChip
                        key={n}
                        onClick={cite(n)}
                        aria-label={`Transcript line ${n}`}
                      >
                        line {n}
                      </RefChip>
                    ))}
                  </div>
                </li>
              ))}
            </ol>
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
      {p.consent ? (
        <label className={styles.row}>
          <input
            type="checkbox"
            checked={p.consent.checked}
            onChange={(e) => p.consent!.onChange(e.target.checked)}
          />{" "}
          Cardholder consented to this verification call
        </label>
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
