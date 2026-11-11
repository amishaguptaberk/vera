'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { ApiError, useCases, useSession } from '@/api';
import { Banner, Skeleton } from '@/design-system/primitives';
import { CaseWorkspace } from '@/features/case';
import { Landing } from '@/features/shell/Landing';
import { PageMain } from '@/features/shell/PageMain';
import { viewForRole } from '@/features/shell/role-view';
import { pageMounts } from './mounts';
import { NotAvailableYet } from './NotAvailableYet';

export { NotAvailableYet };
import styles from './pages.module.css';

export function RequestRoute({ requestId }: { requestId: string }) {
  const Page = pageMounts.RequestPage;
  return Page ? <Page requestId={requestId} /> : <NotAvailableYet>Requests from Finance will appear here once the service is available.</NotAvailableYet>;
}

export function HomePage() {
  const Home = pageMounts.CardholderHome;
  return <Landing cardholder={Home ? <Home /> : <NotAvailableYet>Requests from Finance will appear here once the service is available.</NotAvailableYet>} />;
}

/**
 * Reviewer / card admin landing (prototype reviewer view): the case that waits on a reviewer, opened in the
 * workspace, where the server offers this role its approve / return actions. Which cases wait on a reviewer is
 * the queue's `wait_kind` from the server.
 */
export function ApprovalsPage() {
  const session = useSession();
  const cases = useCases();
  const params = useSearchParams();
  const view = session.data ? viewForRole(session.data.active_role) : null;
  if (session.data && view !== 'reviewer') return <NotAvailableYet title="Approvals are for reviewers.">Switch to the Reviewer · card admin view to see decisions waiting for approval.</NotAvailableYet>;
  if (cases.isError) {
    const e = cases.error;
    return (
      <div className={styles.head}>
        <Banner tone="bad" title={e instanceof ApiError && e.status === 403 ? 'Not available for this role' : 'Could not load approvals'}>
          {e instanceof Error ? e.message : String(e)}
        </Banner>
      </div>
    );
  }
  if (!cases.data || !session.data) {
    return (
      <div className={styles.head} aria-busy="true">
        <Skeleton height={28} width={320} />
      </div>
    );
  }
  const waiting = cases.data.filter((r) => r.wait_kind === 'reviewer' && r.live);
  if (!waiting.length) {
    const live = cases.data.filter((r) => r.live);
    return (
      <PageMain>
        <section className={styles.rvEmpty} data-testid="slot-empty" aria-label="Approvals">
          <div className={styles.rvEye}>
            <span className={styles.rvDot} aria-hidden="true" />
            <span>Reviewer</span>
          </div>
          <h2 className={styles.rvT}>Nothing is waiting for you right now.</h2>
          <p className={styles.rvP}>Decisions sent for review will appear here.</p>
          {live.map((r) => (
            <p key={r.case_id} className={styles.rvP}>
              {r.case_id} · {r.merchant}: {r.state_label}.
            </p>
          ))}
        </section>
      </PageMain>
    );
  }
  const picked = waiting.find((r) => r.case_id === params.get('case')) ?? waiting[0];
  return (
    <div data-testid="approvals">
      {waiting.length > 1 ? (
        <nav className={styles.pick} aria-label="Waiting for approval">
          {waiting.map((r) => (
            <Link key={r.case_id} href={`/approvals?case=${encodeURIComponent(r.case_id)}`} aria-current={r.case_id === picked.case_id ? 'true' : undefined}>
              {r.case_id} · {r.merchant}
            </Link>
          ))}
        </nav>
      ) : null}
      <CaseWorkspace key={picked.case_id} caseId={picked.case_id} />
    </div>
  );
}
