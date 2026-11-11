// Display formatting for server timestamps and statuses (labels only; no business rules).
import type { CommsTone } from '@/components/comms';
import type { CommunicationItem } from './contract';

const DATE = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });
const TIME = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' });

export function fmtAt(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${DATE.format(d)} · ${TIME.format(d)}`;
}

export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : DATE.format(d);
}

export const KIND_LABEL: Record<string, string> = { cardholder_request: 'Cardholder request', follow_up: 'Cardholder follow-up', final: 'Final update' };

export const REVIEW_LABEL: Record<string, string> = {
  complete: 'Complete response · supports the claim',
  incomplete: 'Incomplete response · follow-up required',
  conflicting: 'Conflicting response · decision blocked pending clarification',
};

export function statusOf(i: Pick<CommunicationItem, 'status' | 'response_review'>): { label: string; tone: CommsTone } {
  switch (i.status) {
    case 'drafted':
      return { label: 'Drafted · waiting for your approval', tone: 'cur' };
    case 'sent':
      return { label: 'Sent · waiting for reply', tone: 'wait' };
    case 'reminded':
      return { label: 'Reminder sent · waiting for reply', tone: 'wait' };
    case 'overdue':
      return { label: 'Reply overdue', tone: 'bad' };
    case 'responded':
      return i.response_review === 'none' ? { label: 'Replied · not reviewed', tone: 'cur' } : { label: 'Replied · reviewed', tone: 'ok' };
    default:
      return { label: i.status, tone: 'mute' };
  }
}
