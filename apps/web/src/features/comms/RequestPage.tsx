'use client';

import { CardholderRequestCard, type CardholderSubmission } from '@/components/comms';
import styles from '@/components/comms/Cardholder.module.css';
import type { ResponseAttachment, ResponseIn } from './contract';
import { fmtDay } from './format';
import { isNotDeployed, useCardholderRequest, useSubmitResponse } from './queries';

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

export async function toResponseIn(s: CardholderSubmission): Promise<ResponseIn> {
  const text = s.note.trim() ? `${s.answerLabel}\n\n${s.note.trim()}` : s.answerLabel;
  if (!s.file) return { text };
  const attachment: ResponseAttachment = { file_name: s.file.name.slice(0, 64), content_type: s.file.type, size_bytes: s.file.size, sha256: await sha256Hex(s.file) };
  return { text, attachment };
}

/** Cardholder "Charge review" page for one request (route: /requests/[requestId]). Shows only that request's data. */
export function RequestPage({ requestId }: { requestId: string }) {
  const q = useCardholderRequest(requestId);
  const submit = useSubmitResponse(requestId);
  if (q.isError) {
    return (
      <div className={styles.ctask}>
        <div className={styles.card}>
          <div className={styles.done}>
            <b>{isNotDeployed(q.error) ? 'Not available yet.' : 'This request isn’t available.'}</b>
            <p>{isNotDeployed(q.error) ? 'Requests from Finance will appear here once the service is deployed.' : 'Finance will contact you if they still need anything.'}</p>
          </div>
        </div>
      </div>
    );
  }
  if (!q.data) return <div className={styles.ctask} aria-busy="true" />;
  const r = q.data;
  return (
    <CardholderRequestCard
      request={{ questions: r.questions, dueLabel: r.due_at ? `Please respond by ${fmtDay(r.due_at)}` : null, responded: r.responded }}
      submitting={submit.isPending}
      submitError={submit.error ? submit.error.message : null}
      onSubmit={async (s) => submit.mutate(await toResponseIn(s))}
    />
  );
}
