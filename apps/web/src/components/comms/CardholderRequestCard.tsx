'use client';

import { useState, type ChangeEvent } from 'react';
import { Button } from '@/design-system/primitives';
import styles from './Cardholder.module.css';

/** Only what the cardholder may see: their own questions and deadline (no ids, no staff names). */
export type CardholderRequestProps = {
  questions: readonly string[];
  /** Pre-formatted, e.g. "Please respond by Nov 13". */
  dueLabel: string | null;
  responded: boolean;
};

export type CardholderAnswer = 'did' | 'someone_else' | 'not_sure';

export const ANSWER_LABELS: Readonly<Record<CardholderAnswer, string>> = {
  did: 'I did',
  someone_else: 'Someone else did',
  not_sure: 'I’m not sure',
};

export type CardholderSubmission = { answer: CardholderAnswer; answerLabel: string; note: string; file: File | null };

// Mirrors packages/domain/vera_domain/comms.py ALLOWED_TYPES / MAX_BYTES (the server re-checks).
export const ACCEPTED_TYPES: readonly string[] = ['application/pdf', 'image/png', 'image/jpeg'];
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

const fileSize = (n: number) => (n < 1048576 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`);
const fileExt = (name: string) => (name.split('.').pop() || 'file').toUpperCase().slice(0, 4);

export type CardholderRequestCardProps = {
  request: CardholderRequestProps;
  onSubmit: (s: CardholderSubmission) => void;
  submitting?: boolean;
  /** Server error from the last submit (kept beside the form; the draft stays). */
  submitError?: string | null;
  /** Initial form state (preview of the validation states). */
  initial?: { answer?: CardholderAnswer; note?: string; fileError?: string };
};

/** Port of the prototype's cardholder "Charge review" page (Main.dc.html:1797-1853). */
export function CardholderRequestCard({ request, onSubmit, submitting = false, submitError = null, initial }: CardholderRequestCardProps) {
  const [answer, setAnswer] = useState<CardholderAnswer | null>(initial?.answer ?? null);
  const [note, setNote] = useState(initial?.note ?? '');
  const [file, setFile] = useState<File | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(initial?.fileError ?? null);

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    try {
      e.target.value = '';
    } catch {
      /* jsdom: read-only */
    }
    if (f.size > MAX_FILE_BYTES) return setFileErr(`${f.name} is over 10 MB.`);
    if (!ACCEPTED_TYPES.includes(f.type)) return setFileErr(`${f.name} isn’t a PDF, JPG or PNG.`);
    setFileErr(null);
    setFile(f);
  };

  const [first, ...rest] = request.questions;
  const head = request.responded ? 'Response sent' : 'Confirm this charge';
  const hint = answer ? (file ? '1 file attached' : 'No file attached') : 'Choose an answer first';

  return (
    <div className={styles.ctask}>
      <div className={styles.card}>
        <div className={styles.head}>
          <h2>{head}</h2>
          {!request.responded && request.dueLabel ? <div className={styles.dl}>{request.dueLabel}</div> : null}
        </div>
        {!request.responded ? (
          <div className={styles.body}>
            <div>
              <div className={styles.k}>Finance needs one more detail</div>
              <p className={styles.q} id="chq">
                {first}
              </p>
              {rest.length ? (
                <ul className={styles.qs}>
                  {rest.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              ) : null}
            </div>
            <div className={styles.opts} role="radiogroup" aria-labelledby="chq">
              {(Object.keys(ANSWER_LABELS) as CardholderAnswer[]).map((k) => (
                <label key={k} className={`${styles.opt}${answer === k ? ` ${styles.on}` : ''}`}>
                  <input type="radio" name="chpick" checked={answer === k} onChange={() => setAnswer(k)} />
                  {ANSWER_LABELS[k]}
                </label>
              ))}
            </div>
            <div>
              <div className={styles.k}>
                Attach supporting file <span className={styles['opt-note']}>· optional</span>
              </div>
              <div className={styles.att}>
                <label className={styles.up}>
                  <input type="file" className={styles.sr} accept=".pdf,.jpg,.jpeg,.png" onChange={onFile} aria-label="Attach file" />
                  Attach file
                </label>
                <span className={styles.rd}>PDF, JPG or PNG · up to 10 MB</span>
              </div>
              {file ? (
                <div className={styles.files}>
                  <div className={styles.file}>
                    <span className={styles.nm}>{file.name}</span>
                    <span className={styles.st}>{`${fileExt(file.name)} · ${fileSize(file.size)} · ready to send`}</span>
                    <Button variant={['sm', 'ghost']} onClick={() => setFile(null)} aria-label={`Remove ${file.name}`}>
                      Remove
                    </Button>
                  </div>
                </div>
              ) : null}
              {fileErr ? (
                <div className={styles.err} role="alert">
                  {fileErr}
                </div>
              ) : null}
            </div>
            <div className={styles.field}>
              <label htmlFor="chr">
                Note to Finance <span className={styles.light}>· optional</span>
              </label>
              <textarea id="chr" className={styles.ta} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Anything that helps explain the order" />
            </div>
            {submitError ? (
              <div className={styles.err} role="alert">
                {submitError}
              </div>
            ) : null}
            <div className={styles.foot}>
              <Button
                variant="go"
                disabled={!answer || submitting}
                aria-busy={submitting || undefined}
                onClick={() => answer && onSubmit({ answer, answerLabel: ANSWER_LABELS[answer], note, file })}
              >
                Send response
              </Button>
              <span className={styles.rd}>{hint}</span>
            </div>
          </div>
        ) : (
          <div className={styles.done}>
            <b>Nothing is waiting for you right now.</b>
            <p>Thanks — Finance has your response. Finance will contact you only if something else is needed.</p>
          </div>
        )}
      </div>
      <p className={styles.pageFoot}>Files you attach are recorded for Finance. They don’t confirm anything on their own.</p>
    </div>
  );
}
