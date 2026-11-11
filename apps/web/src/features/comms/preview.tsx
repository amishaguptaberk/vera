// Development preview of every communications state, rendered with the REAL presentational components and
// fixtures from ./dev-fixtures (imported nowhere else). Mounted by the integrator's /preview route only.
import type { ReactNode } from 'react';
import { CardholderRequestCard, CommsActions, CommsList, DraftEditor, FollowupTaskBlock, MessageDetail, type CommsAction } from '@/components/comms';
import type { CommunicationDetail } from './contract';
import { CARDHOLDER_NAME, cardholderRequest, draftDetail, draftItem, overdueDetail, respondedDetail, sentDetail } from './dev-fixtures/chg-1042';
import { KIND_LABEL, REVIEW_LABEL, fmtAt, fmtDay, statusOf } from './format';

const noop = () => {};
const act = (command: string, label: string, ghost = false): CommsAction => ({ command, label, enabled: true, ghost });

function detail(c: CommunicationDetail, children: ReactNode) {
  const r = c.response;
  return (
    <MessageDetail
      kind={KIND_LABEL[c.kind] ?? 'Cardholder request'}
      id={c.id}
      kv={[
        { k: 'To', v: CARDHOLDER_NAME },
        { k: 'Channel', v: c.channel ? 'Email' : 'Not sent' },
        { k: 'Sent', v: c.status === 'drafted' ? 'Not sent' : fmtAt(c.at) },
        { k: 'Status', v: statusOf(c).label },
        ...(c.due_at && !r ? [{ k: 'Reply due', v: fmtDay(c.due_at) }] : []),
      ]}
      origLabel="Original request"
      body={c.body}
      response={
        r
          ? {
              meta: `${r.id} · ${fmtAt(r.submitted_at)}`,
              text: r.text,
              isNew: c.response_review === 'none',
              kv: [
                { k: 'Attachments', v: r.evidence_record_id ?? 'None' },
                { k: 'Fact status', v: 'Claim · not reviewed yet — nothing is verified by opening it' },
                ...(REVIEW_LABEL[c.response_review] ? [{ k: 'Assessment', v: REVIEW_LABEL[c.response_review] }] : []),
              ],
            }
          : null
      }
      questions={r ? c.questions : []}
      onBack={noop}
    >
      {children}
    </MessageDetail>
  );
}

const editor = (send: boolean) => (
  <DraftEditor
    to={CARDHOLDER_NAME}
    subject={draftDetail.subject}
    body={draftDetail.body}
    channel="email"
    send={send ? { label: 'Approve and send', enabled: true } : null}
    canSave={false}
    onChange={noop}
    onSave={noop}
    onSend={noop}
  />
);
const SAFE = 'Message sent once · retrying checks the existing delivery result before sending again';

export const previewStates: { name: string; render: () => ReactNode }[] = [
  { name: 'Communications · empty', render: () => <CommsList rows={[]} onOpen={noop} /> },
  {
    name: 'Communications · list',
    render: () => <CommsList rows={[draftItem, { ...sentDetail, id: 'MSG-2202' }].map((i) => ({ id: i.id, kind: 'Message', title: i.title, status: statusOf(i).label, tone: statusOf(i).tone, at: fmtAt(i.at) }))} onOpen={noop} />,
  },
  { name: 'Task card · draft (approve and send)', render: () => <FollowupTaskBlock step="draft" cardholderName={CARDHOLDER_NAME}>{editor(true)}</FollowupTaskBlock> },
  { name: 'Task card · draft (send not offered yet)', render: () => <FollowupTaskBlock step="draft" cardholderName={CARDHOLDER_NAME}>{editor(false)}</FollowupTaskBlock> },
  { name: 'Message detail · draft', render: () => detail(draftDetail, editor(true)) },
  { name: 'Task card · waiting', render: () => <FollowupTaskBlock step="waiting" cardholderName={CARDHOLDER_NAME} /> },
  { name: 'Message detail · sent', render: () => detail(sentDetail, <CommsActions actions={[act('send_reminder', 'Send reminder')]} safe={SAFE} onAction={noop} />) },
  { name: 'Task card · overdue (noresp1)', render: () => <FollowupTaskBlock step="noresp1" cardholderName={CARDHOLDER_NAME} /> },
  { name: 'Message detail · overdue', render: () => detail(overdueDetail, <CommsActions actions={[act('send_reminder', 'Send reminder')]} safe={SAFE} onAction={noop} />) },
  { name: 'Task card · no reply after follow-up (noresp2)', render: () => <FollowupTaskBlock step="noresp2" cardholderName={CARDHOLDER_NAME} /> },
  {
    name: 'Task card · response',
    render: () => <FollowupTaskBlock step="response" cardholderName={CARDHOLDER_NAME} responseText={respondedDetail.response!.text} responseAttached />,
  },
  {
    name: 'Message detail · response (New)',
    render: () =>
      detail(
        respondedDetail,
        <CommsActions actions={['Complete', 'Incomplete', 'Conflicting'].map((o) => act(`review:${o}`, `Mark ${o.toLowerCase()}`))} safe={SAFE} onAction={noop} />,
      ),
  },
  { name: 'Message detail · response reviewed', render: () => detail({ ...respondedDetail, response_review: 'incomplete' }, null) },
  {
    name: 'Cardholder · request',
    render: () => <CardholderRequestCard request={{ questions: cardholderRequest.questions, dueLabel: `Please respond by ${fmtDay(cardholderRequest.due_at)}`, responded: false }} onSubmit={noop} />,
  },
  {
    name: 'Cardholder · file over 10 MB (draft kept)',
    render: () => (
      <CardholderRequestCard
        request={{ questions: cardholderRequest.questions, dueLabel: `Please respond by ${fmtDay(cardholderRequest.due_at)}`, responded: false }}
        initial={{ answer: 'did', note: 'Ordered for the Plant Ops line.', fileError: 'Northstar_invoice_scan.pdf is over 10 MB.' }}
        onSubmit={noop}
      />
    ),
  },
  { name: 'Cardholder · response sent', render: () => <CardholderRequestCard request={{ questions: cardholderRequest.questions, dueLabel: null, responded: true }} onSubmit={noop} /> },
];
