'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ApiError } from '@/api/client';
import { runCommand } from '@/api/commands';
import { useCaseView, type ActionView, type CaseView } from '@/api/queries';
import { CommsActions, CommsList, DraftEditor, MessageDetail, type CommsAction, type DraftChannel } from '@/components/comms';
import styles from '@/components/comms/Comms.module.css';
import { COMMS_COMMANDS, type CommunicationDetail } from './contract';
import { useLocalDraft } from './drafts';
import { KIND_LABEL, REVIEW_LABEL, fmtAt, fmtDay, statusOf } from './format';
import { isNotDeployed, useCommunication, useCommunications } from './queries';

const REVIEW_OUTCOMES = [
  { outcome: 'complete', label: 'Complete' },
  { outcome: 'incomplete', label: 'Incomplete' },
  { outcome: 'conflicting', label: 'Conflicting' },
] as const;

const DETAIL_COMMANDS: readonly string[] = [COMMS_COMMANDS.remind, COMMS_COMMANDS.draft];

const offered = (view: CaseView | undefined, command: string) => view?.available_actions.find((a) => a.command === command) ?? null;

export const NotAvailableYet = () => <p className={styles.unavail}>Not available yet. Communications for this case will appear here once the service is deployed.</p>;

/** Case workspace "Communications" tab (prototype Main.dc.html:1739-1777). */
export function CommsPanel({ caseId }: { caseId: string }) {
  const [sel, setSel] = useState<string | null>(null);
  const list = useCommunications(caseId);
  if (list.isError) return <div className={styles.cmx}>{isNotDeployed(list.error) ? <NotAvailableYet /> : <p className={styles.rd}>{list.error.message}</p>}</div>;
  if (!list.data) return <div className={styles.cmx} aria-busy="true" />;
  const has = sel && list.data.some((i) => i.id === sel);
  return (
    <div className={styles.cmx}>
      {has ? (
        <CommsMessage caseId={caseId} itemId={sel!} onBack={() => setSel(null)} />
      ) : (
        <CommsList
          rows={list.data.map((i) => {
            const st = statusOf(i);
            return { id: i.id, kind: 'Message', title: i.title, status: st.label, tone: st.tone, at: fmtAt(i.at) };
          })}
          onOpen={setSel}
        />
      )}
    </div>
  );
}

function CommsMessage({ caseId, itemId, onBack }: { caseId: string; itemId: string; onBack: () => void }) {
  const item = useCommunication(caseId, itemId);
  const view = useCaseView(caseId);
  if (item.isError) return isNotDeployed(item.error) ? <NotAvailableYet /> : <p className={styles.rd}>{item.error.message}</p>;
  if (!item.data) return <div aria-busy="true" />;
  const c = item.data;
  const r = c.response;
  const kv = [
    { k: 'To', v: view.data?.cardholder.name ?? 'Cardholder' },
    { k: 'Channel', v: c.channel ? (c.channel === 'portal' ? 'Ramp app' : 'Email') : 'Not sent' },
    { k: 'Sent', v: c.status === 'drafted' ? 'Not sent' : fmtAt(c.at) },
    { k: 'Status', v: statusOf(c).label },
    ...(c.due_at && !r ? [{ k: 'Reply due', v: fmtDay(c.due_at) }] : []),
    ...(c.reminders ? [{ k: 'Reminders', v: String(c.reminders) }] : []),
  ];
  const response = r
    ? {
        meta: `${r.id} · ${fmtAt(r.submitted_at)}`,
        text: r.text,
        isNew: c.response_review === 'none',
        kv: [
          { k: 'Attachments', v: r.evidence_record_id ?? 'None' },
          {
            k: 'Fact status',
            v: c.response_review === 'none' ? 'Claim · not reviewed yet — nothing is verified by opening it' : 'Claim · reviewed',
          },
          ...(REVIEW_LABEL[c.response_review] ? [{ k: 'Assessment', v: REVIEW_LABEL[c.response_review] }] : []),
        ],
      }
    : null;
  return (
    <MessageDetail
      kind={KIND_LABEL[c.kind] ?? 'Cardholder request'}
      id={c.id}
      kv={kv}
      origLabel="Original request"
      body={c.body}
      response={response}
      questions={r ? c.questions : []}
      onBack={onBack}
    >
      {c.status === 'drafted' ? (
        <CommsDraft caseId={caseId} item={c} view={view.data} />
      ) : (
        <CommsSentActions caseId={caseId} view={view.data} reviewable={!!r} />
      )}
    </MessageDetail>
  );
}

/** Draft editor wired to the server: Send only as offered; edits kept in the local drafts store until saved/sent. */
export function CommsDraft({ caseId, item, view }: { caseId: string; item: CommunicationDetail; view: CaseView | undefined }) {
  const qc = useQueryClient();
  const { draft, update, clear } = useLocalDraft(caseId, item.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const subject = draft?.subject ?? item.subject;
  const body = draft?.body ?? item.body;
  const channel: DraftChannel = draft?.channel ?? (item.channel === 'portal' ? 'portal' : 'email');
  const dirty = subject !== item.subject || body !== item.body;
  const send = offered(view, COMMS_COMMANDS.send);
  const save = offered(view, COMMS_COMMANDS.update);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as ApiError).blockedReason ?? (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const doSave = async (v: CaseView, a: ActionView) => (await runCommand(qc, caseId, v.case_version, a, { subject, body })).case;

  return (
    <DraftEditor
      to={view?.cardholder.name ?? 'Cardholder'}
      subject={subject}
      body={body}
      channel={channel}
      savedNote={dirty ? 'Edited · not saved' : item.draft_versions > 1 ? `Saved as version ${item.draft_versions}` : null}
      send={send ? { label: send.label, enabled: send.enabled, blockedReason: send.blocked_reason } : null}
      canSave={!!save && save.enabled && dirty}
      busy={busy}
      error={error}
      onChange={update}
      onSave={() =>
        run(async () => {
          if (view && save) await doSave(view, save);
          clear();
        })
      }
      onSend={() =>
        run(async () => {
          if (!view || !send) return;
          let v = view;
          let a: ActionView = send;
          if (dirty && save) {
            v = await doSave(view, save);
            const next = v.available_actions.find((x) => x.command === COMMS_COMMANDS.send);
            if (!next || !next.enabled) return clear();
            a = next;
          }
          await runCommand(qc, caseId, v.case_version, a, { channel, subject, attachments: [] });
          clear();
        })
      }
    />
  );
}

function CommsSentActions({ caseId, view, reviewable }: { caseId: string; view: CaseView | undefined; reviewable: boolean }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!view) return null;
  const review = reviewable ? offered(view, COMMS_COMMANDS.review) : null;
  const actions: CommsAction[] = [
    ...(review ? REVIEW_OUTCOMES.map((o) => ({ command: `${review.command}:${o.outcome}`, label: `Mark ${o.label.toLowerCase()}`, enabled: review.enabled, blockedReason: review.blocked_reason })) : []),
    ...view.available_actions
      .filter((a) => DETAIL_COMMANDS.includes(a.command))
      .map((a) => ({ command: a.command, label: a.label, enabled: a.enabled, blockedReason: a.blocked_reason, ghost: a.style === 'ghost' })),
  ];
  const onAction = async (cmd: string) => {
    const [name, outcome] = cmd.split(':');
    const a = view.available_actions.find((x) => x.command === name);
    if (!a) return;
    setBusy(cmd);
    setError(null);
    try {
      await runCommand(qc, caseId, view.case_version, a, outcome ? { outcome } : {});
    } catch (e) {
      setError((e as ApiError).blockedReason ?? (e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <>
      <CommsActions actions={actions} busy={busy} safe="Message sent once · retrying checks the existing delivery result before sending again" onAction={onAction} />
      {error ? (
        <p className={styles.rd} role="alert">
          {error}
        </p>
      ) : null}
    </>
  );
}
