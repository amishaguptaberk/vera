'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useCaseView, useRunCommand, useSession } from '@/api';
import { CardholderVerify } from '@/components/verify';
import { formatMoney } from '@/lib';
import { CARDHOLDER_COMMANDS } from './contract';
import { outboxQuery } from './queries';
import styles from './verify.module.css';

/**
 * Cardholder role: "Verify it's you". The only place a code can appear is the labelled synthetic demo box,
 * fed by the cardholder-only outbox route. The code is never logged, put in a URL, or cached under a staff key.
 */
export function CardholderVerifyPanel({ caseId }: { caseId: string }) {
  const cv = useCaseView(caseId);
  const session = useSession();
  const run = useRunCommand(caseId);
  const [val, setVal] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const c = cv.data;
  const action = c?.available_actions.find((a) => a.command === CARDHOLDER_COMMANDS.submitOtp || a.command === CARDHOLDER_COMMANDS.answerPush) ?? null;
  const vid = (action?.payload_defaults.verification_id as string | undefined) ?? null;
  const isCardholder = session.data?.active_role === 'cardholder';
  const synthetic = session.data?.environment === 'synthetic';
  const box = useQuery({ ...outboxQuery(caseId, vid ?? ''), enabled: !!vid && isCardholder && synthetic && action?.command === CARDHOLDER_COMMANDS.submitOtp });

  if (!c || !isCardholder) return null;
  if (!action && !done) return <p className={styles.rd}>No verification request is waiting for you.</p>;
  const t = c.transaction;
  const meta = [`${t.merchant} · ${formatMoney(t.amount_cents, t.currency)}`, `Card ending ${t.card_last4}`];
  const verified = done === 'verified';
  const submit = (payload: Record<string, unknown>) => {
    if (!action) return;
    run.mutate(
      { action, caseVersion: c.case_version, payload },
      {
        onSuccess: (out) => {
          setVal('');
          const st = (out.result as { status?: string } | undefined)?.status;
          if (st && st !== 'requested') setDone(st);
        },
      },
    );
  };
  return (
    <CardholderVerify
      heading={done ? (verified ? 'You’re verified' : 'Verification not completed') : 'Verify your identity'}
      meta={meta}
      channel={action?.command === CARDHOLDER_COMMANDS.answerPush ? 'push' : 'otp'}
      text={`Finance is reviewing the ${formatMoney(t.amount_cents, t.currency)} ${t.merchant} charge and needs to confirm it’s you before calling. This doesn’t decide anything about the charge.`}
      demo={synthetic && box.data ? { label: box.data.label, code: box.data.code } : null}
      value={val}
      onChange={setVal}
      onSubmit={() => submit({ code: val })}
      onApprove={() => submit({ approve: true })}
      onDeny={() => submit({ approve: false })}
      expiry={box.data ? `${box.data.attempts_left} ${box.data.attempts_left === 1 ? 'attempt' : 'attempts'} left` : undefined}
      message={run.error?.message ?? null}
      busy={run.isPending}
      done={
        done
          ? verified
            ? { title: 'Thanks — you’re verified.', text: 'Finance may call the number on file to ask about the charge. Finance will never ask you for a code on the call.' }
            : { title: 'Verification didn’t complete.', text: 'Nothing about your charge was decided. Finance will contact you through the number or email on file.' }
          : null
      }
    />
  );
}
