import type { ReactNode } from 'react';
import styles from './Comms.module.css';

export type FollowupStep = 'draft' | 'waiting' | 'noresp1' | 'noresp2' | 'response';

export type FollowupTaskBlockProps = {
  step: FollowupStep;
  /** Display name of the cardholder from the case view; falls back to "the cardholder". */
  cardholderName?: string | null;
  followUp?: boolean;
  /** Draft step only: false until the server holds a drafted message (the copy must not claim one exists). */
  drafted?: boolean;
  reminders?: number;
  responseText?: string | null;
  responseAttached?: boolean;
  /** Draft editor or actions row, supplied by the feature. */
  children?: ReactNode;
};

/** Copy for the follow-up steps of the task card (prototype Main.dc.html:4026-4032). */
export function followupCopy(p: FollowupTaskBlockProps): { title: string; paras: string[] } {
  const who = p.cardholderName?.split(' ')[0] || 'the cardholder';
  switch (p.step) {
    case 'draft':
      return {
        title: p.followUp ? 'Send one targeted follow-up.' : `Ask ${who} for the missing receipt and the amount difference.`,
        paras: [
          p.drafted === false
            ? `Cardholder Follow-up drafts it from the findings. It doesn’t re-ask what ${who} already reported. Nothing is sent until you approve.`
            : `Drafted by Cardholder Follow-up. It doesn’t re-ask what ${who} already reported. Nothing is sent until you approve.`,
        ],
      };
    case 'waiting':
      return {
        title: p.followUp ? `Follow-up sent to ${who}` : `Request sent to ${who}`,
        paras: [p.reminders ? 'Reminder sent. Their reply will appear here and in Evidence.' : 'Their reply will appear here and in Evidence. Send a reminder if it’s needed.'],
      };
    case 'noresp1':
      return { title: 'Cardholder response overdue', paras: ['The first request was not answered by its deadline.'] };
    case 'noresp2':
      return { title: 'No reply after the follow-up', paras: ['Vera won’t send more follow-ups. Close as unresolved or reassign.'] };
    case 'response':
      return {
        title: `${who.charAt(0).toUpperCase()}${who.slice(1)} replied.`,
        paras: [`“${p.responseText ?? ''}”`, `${p.responseAttached ? 'Attachment recorded. ' : 'No attachments. '}Recorded as a claim.`],
      };
  }
}

/** Body of the task card for the follow-up steps: title, paragraphs, then the feature's editor/actions. */
export function FollowupTaskBlock(p: FollowupTaskBlockProps) {
  const c = followupCopy(p);
  return (
    <div data-step={p.step}>
      <h2 className={styles.taskTitle}>{c.title}</h2>
      {c.paras.map((t) => (
        <p key={t} className={styles.taskP}>
          {t}
        </p>
      ))}
      {p.children}
    </div>
  );
}
