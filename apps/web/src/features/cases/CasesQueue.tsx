'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { ApiError, filterCountsQuery, useCases, useCasesSummary, useSession } from '@/api';
import { Banner, Skeleton } from '@/design-system/primitives';
import { formatMoney } from '@/lib';
import { FILTERS, SORTS, filterCount, parseFilter, parseSort, visibleRows, type FilterId, type QueueRowExt, type SortId } from './queue-filters';
import { summaryTiles } from './summary';
import styles from './CasesQueue.module.css';

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');

export function caseHref(id: string) {
  return `/cases/${encodeURIComponent(id)}`;
}

export function SummaryStrip() {
  const summary = useCasesSummary();
  const tiles = summaryTiles(summary.data);
  if (summary.isPending) {
    return <Skeleton height={92} radius={12} />;
  }
  if (!tiles.length) return null; // includes a typed 403 for roles the queue is not for
  return (
    <dl className={cx(styles.sumstrip, tiles.length > 4 && styles.many)} aria-label="Open charge exposure" data-parity="sumstrip">
      {tiles.map((t) => (
        <div key={t.key} className={cx(styles.ss, t.primary && styles.lead)} title={t.definition ?? undefined}>
          <dt>
            {t.label}
            {t.basis ? <span className={styles.basis}> · {t.basis}</span> : null}
          </dt>
          <dd className={styles.mv4}>{formatMoney(t.amountCents, t.currency, true)}</dd>
          <dd className={cx(styles.cnt, t.key === 'overdue' && (t.count ?? 0) > 0 && styles.over)}>
            {t.count === null ? '' : t.key === 'overdue' && t.count === 0 ? 'None' : t.key === 'temporary_credit' ? `${t.count} issued` : `${t.count} ${t.count === 1 ? 'case' : 'cases'}`}
          </dd>
          {t.definition ? <dd className={styles.srOnly}>{t.definition}</dd> : null}
        </div>
      ))}
    </dl>
  );
}

function Row({ r }: { r: QueueRowExt }) {
  const name = `${r.case_id} · ${r.merchant}`;
  return (
    <tr className={r.live ? cx(styles.sel, styles.live) : styles.ex} data-openable={r.live ? 'true' : 'false'}>
      <td>
        <div className={styles.cqT}>
          {r.live ? (
            <Link className={styles.caseL} href={caseHref(r.case_id)}>
              {name}
            </Link>
          ) : (
            <span className={styles.cn}>{name}</span>
          )}
          <div className={styles.sub}>
            <span className={styles.ramt}>{formatMoney(r.amount_cents, r.currency)}</span> · {r.state_label}
          </div>
        </div>
      </td>
      {/* Server strings when present; "—" otherwise. Nothing is invented. */}
      <td className={cx(styles.blk, !r.blocker && styles.none)}>{r.blocker || '—'}</td>
      <td>
        <span className={styles.nx}>
          <span>{r.next_action || '—'}</span>
        </span>
      </td>
      <td className={styles.ow}>{r.owner.name}</td>
      <td className={cx(styles.due, r.due?.overdue && styles.over, !r.due?.overdue && r.due_today && styles.today)}>{r.due?.label ?? 'No deadline'}</td>
    </tr>
  );
}

export function CasesQueue() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filter = parseFilter(params.get('filter'));
  const sort = parseSort(params.get('sort'));
  const cases = useCases();
  const session = useSession();
  const me = session.data?.user.id ?? null;
  const counts = useQuery(filterCountsQuery);
  const rows: QueueRowExt[] = cases.data ?? [];
  const shown = visibleRows(rows, filter, sort, me);

  const setParam = (k: 'filter' | 'sort', v: FilterId | SortId, dflt: string) => {
    const next = new URLSearchParams(params.toString());
    if (v === dflt) next.delete(k);
    else next.set(k, v);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  // The queue is staff-only on the server: a typed 403 shows the server's message instead of the queue.
  if (cases.error instanceof ApiError && cases.error.status === 403) {
    return (
      <div className={styles.ov}>
        <div className={styles.pgH}>
          <h1 className={styles.pgT}>Cases</h1>
        </div>
        <Banner tone="info" title="The case queue is not available in this view">
          {cases.error.message}
        </Banner>
      </div>
    );
  }
  return (
    <div className={styles.ov}>
      <div className={styles.pgH} data-parity="page-head">
        <h1 className={styles.pgT}>Cases</h1>
        {cases.dataUpdatedAt ? <span className={styles.pgNow}>Updated {new Date(cases.dataUpdatedAt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}</span> : null}
      </div>
      <SummaryStrip />
      {cases.isError ? (
        <Banner tone="bad" title="Could not refresh the queue" action={{ label: 'Retry', onClick: () => void cases.refetch() }}>
          {(cases.error as Error).message}
          {cases.data ? ' Showing the last loaded cases.' : ''}
        </Banner>
      ) : null}
      <section className={styles.tcard} aria-labelledby="wtr" data-parity="queue">
        <div className={styles.tcardH} data-parity="queue-bar">
          <div className={styles.tcardL}>
            <h2 id="wtr">Case queue</h2>
            <div className={styles.sortc} role="group" aria-label="Sort cases">
              <span>Sort:</span>
              {SORTS.map((o) => (
                <button key={o.id} type="button" className={cx(styles.fb, sort === o.id && styles.on)} aria-pressed={sort === o.id} onClick={() => setParam('sort', o.id, 'priority')}>
                  {/* The label sits in a span like the prototype's, so `.sortc span` gives the underline its 4px tail. */}
                  <span>{o.label}</span>
                </button>
              ))}
            </div>
          </div>
          <div className={styles.filt} role="group" aria-label="Filter cases">
            {FILTERS.map((f) => (
              <button key={f.id} type="button" className={cx(styles.fb, filter === f.id && styles.on)} aria-pressed={filter === f.id} onClick={() => setParam('filter', f.id, 'all')}>
                {f.label}
                {f.id !== 'all' && filterCount(counts.data, f.id) !== null ? <span className={styles.fc}>{filterCount(counts.data, f.id)}</span> : null}
              </button>
            ))}
          </div>
        </div>
        <div className={styles.twrap} tabIndex={0} role="region" aria-label="Case queue, scrolls horizontally">
          <table className={styles.wt} aria-busy={cases.isFetching}>
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">What’s blocking it</th>
                <th scope="col">Next action</th>
                <th scope="col">Owner</th>
                <th scope="col">Due</th>
              </tr>
            </thead>
            <tbody>
              {cases.isPending
                ? [0, 1, 2, 3].map((i) => (
                    <tr key={i} data-skeleton="true">
                      <td colSpan={5}>
                        <Skeleton height={36} />
                      </td>
                    </tr>
                  ))
                : shown.map((r) => <Row key={r.case_id} r={r} />)}
            </tbody>
          </table>
        </div>
        {cases.data && shown.length === 0 ? <p className={styles.tnote}>No cases match this filter.</p> : null}
        {shown.some((r) => !r.live) ? <p className={styles.tnote}>Cases without a link are examples and can’t be opened.</p> : null}
      </section>
    </div>
  );
}
