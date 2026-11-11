import type { AskResponse } from './contract';

export type RailPair = { id: number; question: string; response: AskResponse; signature: string };

let seq = 0;

/** Dedup key from the server's answer only; question text is never interpreted client-side. */
export const signatureOf = (r: AskResponse) =>
  r.signature ?? `${r.intent ?? ''}|${r.answer}|${r.citations.map((c) => `${c.record_id}@${c.version ?? ''}`).join(',')}`;

/** Appends a question/answer pair; an earlier pair with the same signature is removed (prototype `ask`). */
export function addPair(pairs: readonly RailPair[], question: string, response: AskResponse): RailPair[] {
  const signature = signatureOf(response);
  return [...pairs.filter((p) => p.signature !== signature), { id: ++seq, question, response, signature }];
}
