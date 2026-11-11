'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useCaseView, useRunCommand, type ActionView } from '@/api';
import { ActionBar } from '@/components/case';
import { ChannelChoice, IdentityDetail, type KV } from '@/components/verify';
import { Skeleton } from '@/design-system/primitives';
import { RESEND_COOLDOWN_SECONDS, type VerificationView } from './contract';
import { CHANNEL, IDENTITY_NEXT, IDENTITY_STATUS, time } from './labels';
import { errorText, verificationsQuery } from './queries';
import styles from './verify.module.css';

export type IdentityPanelProps = { caseId: string; onOpenSource?: (id: string) => void; onBack?: () => void; showActions?: boolean };

/** Rows shown to staff. Built from named fields only: nothing else in a payload (e.g. a stray `code`) can render. */
export function identityRows(v: VerificationView, holder: string): KV[] {
  return [
    { k: 'Channel', v: CHANNEL[v.channel].label },
    { k: 'Bound to', v: `${v.case_id} · ${holder}` },
    { k: 'Sent', v: `${time(v.last_sent_at)} · expires ${time(v.expires_at)}` },
    v.channel === 'push' ? { k: 'Method', v: 'Approve or decline in the Ramp app' } : { k: 'Attempts', v: `${v.attempts} of ${v.max_attempts}` },
    { k: 'Status', v: v.status === 'verified' && v.resolved_at ? `${IDENTITY_STATUS.verified} · ${time(v.resolved_at)}` : IDENTITY_STATUS[v.status] },
  ];
}

export function identityHistory(v: VerificationView): string[] {
  const h = [`${time(v.sent_at)} · Request sent · ${CHANNEL[v.channel].sub.toLowerCase()}`];
  if (v.sends > 1) h.push(`${time(v.last_sent_at)} · Request resent (${v.sends} sends)`);
  if (v.attempts > 0 && v.channel === 'otp') h.push(`Cardholder entries · ${v.attempts} of ${v.max_attempts}`);
  if (v.resolved_at) h.push(`${time(v.resolved_at)} · ${IDENTITY_STATUS[v.status]}`);
  return h;
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export function IdentityPanel({ caseId, onOpenSource, onBack, showActions = true }: IdentityPanelProps) {
  const cv = useCaseView(caseId);
  const q = useQuery(verificationsQuery(caseId));
  const run = useRunCommand(caseId);
  const [channel, setChannel] = useState<'otp' | 'push'>('otp');
  const v = q.data?.length ? q.data[q.data.length - 1] : null;
  const now = useNow(v?.status === 'requested');

  if (q.isPending) return <div aria-busy="true"><Skeleton height={80} /></div>;
  if (q.isError) {
    return <p className={styles.rd}>{errorText(q.error, 'Identity verification is not available yet.')}</p>;
  }
  const c = cv.data;
  const actions = c?.available_actions ?? [];
  const canSend = actions.some((a) => a.command === 'send_verification_request' && a.enabled);
  const onAction = (a: ActionView) => {
    if (!c) return;
    const payload: Record<string, unknown> = a.command === 'send_verification_request' ? { channel } : v && a.command.endsWith('verification_request') ? { verification_id: v.id } : {};
    run.mutate({ action: a, caseVersion: c.case_version, payload });
  };
  const bar = showActions && c ? <ActionBar actions={actions} blocked={c.blocked_actions} busy={run.isPending ? (run.variables?.action.command ?? null) : null} onAction={onAction} /> : null;
  const chooser = canSend ? <ChannelChoice options={(['otp', 'push'] as const).map((k) => ({ key: k, ...CHANNEL[k] }))} value={channel} onChange={(k) => setChannel(k as 'otp' | 'push')} /> : null;

  if (!v) {
    return (
      <div data-testid="identity-detail">
        <p className={styles.rd}>No verification request yet.</p>
        {chooser}
        {bar}
      </div>
    );
  }
  const readyAt = Date.parse(v.last_sent_at) + RESEND_COOLDOWN_SECONDS * 1000;
  const left = Math.ceil((readyAt - now) / 1000);
  const cooldown = v.status === 'requested' && left > 0 ? `Resend available in ${left}s` : null;
  const holder = c?.cardholder.name ?? 'cardholder';
  return (
    <IdentityDetail
      rows={identityRows(v, holder)}
      history={identityHistory(v)}
      result={v.status === 'verified' ? `${holder} controls the approved channel.` : 'Identity not verified.'}
      resultRows={[
        { k: 'What this proves', v: 'Control of the approved channel only · it doesn’t mark the charge authorized or unauthorized' },
        { k: 'Next', v: IDENTITY_NEXT[v.status] },
      ]}
      sources={[v.case_id]}
      onOpenSource={onOpenSource}
      cooldown={cooldown}
      message={run.error?.message ?? (v.status === 'cancelled' ? 'Request cancelled. Send a new request when ready.' : null)}
      actions={
        <>
          {chooser}
          {bar}
        </>
      }
      onBack={onBack}
    />
  );
}
