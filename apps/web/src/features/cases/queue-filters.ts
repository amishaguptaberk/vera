import type { QueueRow } from '@/api';

export type FilterId = 'all' | 'today' | 'over' | 'me' | 'ch' | 'rv';
export type SortId = 'priority' | 'amount';

/** Queue row fields being added by VER-016; read tolerantly until the generated types carry them. */
export type QueueRowExt = QueueRow & {
  blocker?: string | null;
  next_action?: string | null;
  waiting_on?: string | null;
  wait_kind?: 'cardholder' | 'reviewer' | null;
  due_today?: boolean;
};
const waitKind = (r: QueueRowExt) => (r.wait_kind !== undefined ? r.wait_kind : r.state === 'waiting_on_cardholder' ? 'cardholder' : r.state === 'reviewer_pending' ? 'reviewer' : null);

// The prototype's six chips. `countKey` names the field in GET /api/cases/filter-counts.
// Filters read only fields the API returns; they never change case state.
export const FILTERS: readonly { id: FilterId; label: string; countKey: string; match: (r: QueueRowExt, me: string | null) => boolean }[] = [
  { id: 'all', label: 'All', countKey: 'all', match: () => true },
  { id: 'today', label: 'Due today', countKey: 'due_today', match: (r) => r.due_today === true },
  { id: 'over', label: 'Overdue', countKey: 'overdue', match: (r) => !!r.due?.overdue },
  { id: 'me', label: 'Waiting on me', countKey: 'mine', match: (r, me) => me !== null && r.owner.id === me && !waitKind(r) },
  { id: 'ch', label: 'Waiting on cardholder', countKey: 'cardholder', match: (r) => waitKind(r) === 'cardholder' },
  { id: 'rv', label: 'Waiting on reviewer', countKey: 'reviewer', match: (r) => waitKind(r) === 'reviewer' },
];

export const SORTS: readonly { id: SortId; label: string }[] = [
  { id: 'priority', label: 'Priority' },
  { id: 'amount', label: 'Amount ↓' },
];

export const parseFilter = (v: string | null): FilterId => (FILTERS.some((f) => f.id === v) ? (v as FilterId) : 'all');
export const parseSort = (v: string | null): SortId => (v === 'amount' ? 'amount' : 'priority');

/** Priority is the server's order; Amount sorts by the API's integer cents (ordering, not arithmetic). */
export function visibleRows(rows: readonly QueueRowExt[], filter: FilterId, sort: SortId, me: string | null): QueueRowExt[] {
  const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0];
  const out = rows.filter((r) => f.match(r, me));
  if (sort === 'amount') out.sort((a, b) => b.amount_cents - a.amount_cents);
  return out;
}

/** The API's count when GET /api/cases/filter-counts exists; otherwise a count of the returned rows. */
export function filterCount(counts: Record<string, unknown> | null | undefined, rows: readonly QueueRowExt[], id: FilterId, me: string | null): number {
  const f = FILTERS.find((x) => x.id === id) ?? FILTERS[0];
  const fromApi = counts?.[f.countKey];
  if (typeof fromApi === 'number') return fromApi;
  return rows.filter((r) => f.match(r, me)).length;
}
