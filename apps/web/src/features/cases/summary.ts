import type { SummaryBody } from '@/api';

/** One summary tile, as the API states it. `amount_cents`/`count` are passed through, never computed. */
export type SummaryTile = {
  key: string;
  label: string;
  amountCents: number;
  currency: string;
  count: number | null;
  basis: string | null;
  definition: string | null;
  primary: boolean;
};

// New shape (backend change in flight): named metrics `{amount_cents, currency, count, basis, definition}`.
const NEW_ORDER: readonly (readonly [string, string])[] = [
  ['gross_exposure', 'Gross exposure'],
  ['net_exposure', 'Net exposure'],
  ['confirmed_recoveries', 'Confirmed recoveries'],
  ['temporary_credit', 'Temporary credit'],
  ['due_today', 'Due today'],
  ['overdue', 'Overdue'],
];
// Old shape on this base: `{amount_cents, cases}` per metric.
const OLD_ORDER: readonly (readonly [string, string])[] = [
  ['open_exposure', 'Open exposure'],
  ['due_today', 'Due today'],
  ['overdue', 'Overdue'],
  ['temporary_credit', 'Temporary credit'],
];

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null;
const num = (x: unknown) => (typeof x === 'number' && Number.isFinite(x) ? x : null);
const str = (x: unknown) => (typeof x === 'string' && x ? x : null);

/** Adapts whichever summary shape the API returned. Metrics the body does not contain are not shown. */
export function summaryTiles(body: SummaryBody | undefined): SummaryTile[] {
  if (!body) return [];
  const isNew = isObj(body.gross_exposure);
  const order = isNew ? NEW_ORDER : OLD_ORDER;
  const primaryKey = isNew ? 'gross_exposure' : 'open_exposure';
  const out: SummaryTile[] = [];
  for (const [key, label] of order) {
    const m = body[key];
    if (!isObj(m)) continue;
    const amount = num(m.amount_cents);
    if (amount === null) continue;
    out.push({
      key,
      label,
      amountCents: amount,
      currency: str(m.currency) ?? 'USD',
      count: num(m.count) ?? num(m.cases),
      basis: str(m.basis),
      definition: str(m.definition),
      primary: key === primaryKey,
    });
  }
  return out;
}
