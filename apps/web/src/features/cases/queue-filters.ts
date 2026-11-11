import type { QueueRow } from '@/api';

export type FilterId = 'all' | 'over' | 'me' | 'ch' | 'rv';
export type SortId = 'priority' | 'amount';

// Filters read only fields the API returns (`due.overdue`, `state`, `owner.id`); they never change case state.
// "Due today" is not offered: QueueRow has no field that says a row is due today (see INTEGRATION NOTES).
export const FILTERS: readonly { id: FilterId; label: string; match: (r: QueueRow, me: string | null) => boolean }[] = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'over', label: 'Overdue', match: (r) => !!r.due?.overdue },
  { id: 'me', label: 'Waiting on me', match: (r, me) => me !== null && r.owner.id === me && r.state !== 'waiting_on_cardholder' && r.state !== 'reviewer_pending' },
  { id: 'ch', label: 'Waiting on cardholder', match: (r) => r.state === 'waiting_on_cardholder' },
  { id: 'rv', label: 'Waiting on reviewer', match: (r) => r.state === 'reviewer_pending' },
];

export const SORTS: readonly { id: SortId; label: string }[] = [
  { id: 'priority', label: 'Priority' },
  { id: 'amount', label: 'Amount ↓' },
];

export const parseFilter = (v: string | null): FilterId => (FILTERS.some((f) => f.id === v) ? (v as FilterId) : 'all');
export const parseSort = (v: string | null): SortId => (v === 'amount' ? 'amount' : 'priority');

/** Priority is the server's order; Amount sorts by the API's integer cents (ordering, not arithmetic). */
export function visibleRows(rows: readonly QueueRow[], filter: FilterId, sort: SortId, me: string | null): QueueRow[] {
  const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0];
  const out = rows.filter((r) => f.match(r, me));
  if (sort === 'amount') out.sort((a, b) => b.amount_cents - a.amount_cents);
  return out;
}

/** Counts of the rows the API returned (no per-filter counts endpoint exists). */
export const filterCount = (rows: readonly QueueRow[], id: FilterId, me: string | null) =>
  rows.filter((r) => (FILTERS.find((x) => x.id === id) ?? FILTERS[0]).match(r, me)).length;
