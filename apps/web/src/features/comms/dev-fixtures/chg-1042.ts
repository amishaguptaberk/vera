// DEVELOPMENT FIXTURES — imported only by ../preview.tsx. Not live data.
// Contract-conforming (../contract.ts); content from the prototype's CHG-1042 story (Main.dc.html).
import type { CardholderRequest, CommunicationDetail, CommunicationItem } from '../contract';

export const CARDHOLDER_NAME = 'Priya Shah';

const BODY =
  'Hi Priya,\n\nWe’re reviewing the $2,840.00 Bayline Industrial Supply charge on your card ending 4418 (posted Nov 8). We couldn’t find a receipt, and the charge is $440.00 above PO-219.\n\nCould you upload the receipt or invoice, and tell us who ordered the second unit?\n\nThanks,\nSam Rivera, Finance';

export const draftItem: CommunicationItem = {
  id: 'MSG-2201',
  kind: 'cardholder_request',
  status: 'drafted',
  title: 'Receipt and order detail for CHG-1042',
  at: '2026-11-10T15:02:00Z',
  channel: null,
  due_at: null,
  reminders: 0,
  response_review: 'none',
};

export const draftDetail: CommunicationDetail = {
  ...draftItem,
  subject: 'Receipt and order detail for CHG-1042',
  body: BODY,
  questions: ['Please upload the receipt or invoice for the Bayline Industrial Supply charge.', 'Who ordered the second unit?'],
  attachments: [],
  delivery: null,
  draft_versions: 1,
  response: null,
};

export const sentDetail: CommunicationDetail = { ...draftDetail, status: 'sent', channel: 'email', at: '2026-11-10T15:10:00Z', due_at: '2026-11-12T15:10:00Z' };
export const overdueDetail: CommunicationDetail = { ...sentDetail, status: 'overdue', reminders: 1 };
export const respondedDetail: CommunicationDetail = {
  ...sentDetail,
  status: 'responded',
  response: {
    id: 'MSG-2251',
    text: 'I ordered the second unit myself for the Plant Ops line. Receipt attached.',
    evidence_record_id: 'RCP-2201',
    submitted_at: '2026-11-10T16:20:00Z',
  },
};

export const cardholderRequest: CardholderRequest = {
  request_id: 'MSG-2201',
  status: 'awaiting_reply',
  subject: 'Receipt and order detail',
  questions: ['Who ordered the second unit?', 'Please upload the receipt or invoice for the Bayline Industrial Supply charge.'],
  due_at: '2026-11-12T15:10:00Z',
  responded: false,
};
