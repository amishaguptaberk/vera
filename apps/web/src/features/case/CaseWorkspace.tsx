'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { ApiError, useCaseView, useRunCommand, type ActionView, type CaseView } from '@/api';
import { ActionBar } from '@/components/case';
import { Banner, Button, Field, Skeleton, Tabs } from '@/design-system/primitives';
import { formatMoney } from '@/lib';
import { COMMAND_FORMS } from './command-forms';
import styles from './CaseWorkspace.module.css';

export const CASE_TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'decision', label: 'Decision' },
  { id: 'trace', label: 'Run details' },
] as const;
type TabId = (typeof CASE_TABS)[number]['id'];
const parseTab = (v: string | null): TabId => (CASE_TABS.some((t) => t.id === v) ? (v as TabId) : 'overview');

function PolicyBlock({ c }: { c: CaseView }) {
  const p = c.policy;
  return (
    <section className={styles.block} aria-labelledby="pol-h" data-testid="policy-block">
      <h3 id="pol-h">Policy</h3>
      {!p ? (
        <p className={styles.mute}>Not evaluated yet</p>
      ) : (
        <dl className={styles.kv}>
          <dt>Status</dt>
          <dd data-testid="policy-status">{p.status}</dd>
          <dt>Result</dt>
          <dd>{p.label}</dd>
          <dt>Rules failed</dt>
          <dd>{p.rules_failed.length ? p.rules_failed.join(', ') : 'None'}</dd>
          <dt>Evidence used</dt>
          <dd>{p.evidence_used.length ? p.evidence_used.join(', ') : 'None'}</dd>
          <dt>Version</dt>
          <dd>v{p.policy_version}</dd>
        </dl>
      )}
    </section>
  );
}

function ChargeImpact({ c }: { c: CaseView }) {
  const cur = c.transaction.currency;
  const i = c.charge_impact;
  return (
    <section className={styles.block} aria-labelledby="ci-h">
      <h3 id="ci-h">Charge impact</h3>
      <dl className={styles.kv}>
        <dt>Posted</dt>
        <dd>{formatMoney(i.posted_cents, cur)}</dd>
        <dt>Temporary credit</dt>
        <dd>{formatMoney(i.credit_cents, cur)}</dd>
        <dt>Exposure</dt>
        <dd>{formatMoney(i.exposure_cents, cur)}</dd>
      </dl>
      <p className={styles.mute}>{i.note}</p>
    </section>
  );
}

function CommandForm({ action, error, busy, onSubmit, onCancel }: { action: ActionView; error: string | null; busy: boolean; onSubmit: (p: Record<string, string>) => void; onCancel: () => void }) {
  const fields = COMMAND_FORMS[action.command] ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(values);
  };
  return (
    <form className={styles.form} onSubmit={submit} aria-label={action.label}>
      {fields.map((f, i) =>
        f.multiline ? (
          <Field key={f.name} multiline label={f.label} name={f.name} rows={2} value={values[f.name] ?? ''} error={i === 0 && error ? error : undefined} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
        ) : (
          <Field key={f.name} label={f.label} name={f.name} value={values[f.name] ?? ''} error={i === 0 && error ? error : undefined} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
        ),
      )}
      <div className={styles.formActs}>
        <Button type="submit" variant="go" disabled={busy}>
          {action.label}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

export function CaseWorkspace({ caseId }: { caseId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = parseTab(params.get('tab'));
  const sel = params.get('sel');
  const view = useCaseView(caseId);
  const run = useRunCommand(caseId);
  const [formFor, setFormFor] = useState<ActionView | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'warn' | 'bad'; text: string } | null>(null);

  const setParam = (k: 'tab' | 'sel', v: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (v === null) next.delete(k);
    else next.set(k, v);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const c = view.data;
  if (!c) {
    if (view.isError) {
      const e = view.error;
      return (
        <div className={styles.wrap}>
          <Banner tone="bad" title={e instanceof ApiError && e.status === 403 ? 'Not available for this role' : 'Could not load the case'}>
            {e.message}
          </Banner>
        </div>
      );
    }
    return (
      <div className={styles.wrap} aria-busy="true">
        <Skeleton height={28} width={320} />
        <Skeleton height={160} radius={12} />
      </div>
    );
  }

  const execute = (action: ActionView, payload?: Record<string, string>) => {
    setNotice(null);
    setFormError(null);
    run.mutate(
      { action, caseVersion: c.case_version, payload },
      {
        onSuccess: () => setFormFor(null),
        onError: (e) => {
          if (e.code === 'stale_case_version') {
            setFormFor(null);
            setNotice({ tone: 'warn', text: 'This case changed while you were viewing it. The latest version is shown; nothing was retried.' });
          } else if (e.status === 422 && formFor) setFormError(e.message);
          else setNotice({ tone: 'bad', text: e.blockedReason ?? e.message });
        },
      },
    );
  };
  const onAction = (a: ActionView) => {
    if (COMMAND_FORMS[a.command]) {
      setFormError(null);
      setFormFor(a);
    } else execute(a);
  };

  const cur = c.transaction.currency;
  return (
    <div className={styles.wrap} data-step={c.step} data-state={c.state}>
      {view.isError ? <Banner tone="warn">Could not refresh: {view.error.message} Showing the last loaded version.</Banner> : null}
      <header className={styles.head}>
        <div>
          <h1 className={styles.title}>
            {c.case_id} · {c.transaction.merchant}
          </h1>
          <p className={styles.sub}>
            {formatMoney(c.transaction.amount_cents, cur)} · card ••{c.transaction.card_last4} · {c.cardholder.name}
          </p>
        </div>
      </header>
      <dl className={styles.rail} aria-label="Case status">
        <div>
          <dt>State</dt>
          <dd data-testid="case-state">{c.state_label}</dd>
        </div>
        <div>
          <dt>Owner</dt>
          <dd>{c.owner.name}</dd>
        </div>
        <div>
          <dt>Waiting on</dt>
          <dd>{c.waiting_on?.name ?? '—'}</dd>
        </div>
        <div>
          <dt>Due</dt>
          <dd className={c.due?.overdue ? styles.over : undefined}>{c.due?.label ?? 'No deadline'}</dd>
        </div>
      </dl>
      <div className={styles.grid}>
        <section className={styles.task} aria-labelledby="task-h">
          <div className={styles.taskLbl}>Your next step</div>
          <h2 id="task-h" className={styles.taskT} data-testid="next-action">
            {c.next_action}
          </h2>
          {c.hold ? (
            <p className={styles.mute} data-testid="hold-info">
              On hold: {c.hold.reason}
            </p>
          ) : null}
          {notice ? <Banner tone={notice.tone}>{notice.text}</Banner> : null}
          {formFor ? (
            <CommandForm key={formFor.command} action={formFor} error={formError} busy={run.isPending} onSubmit={(p) => execute(formFor, p)} onCancel={() => setFormFor(null)} />
          ) : (
            <ActionBar actions={c.available_actions} blocked={c.blocked_actions} busy={run.isPending ? (run.variables?.action.command ?? null) : null} onAction={onAction} />
          )}
        </section>
        <aside className={styles.side}>
          <ChargeImpact c={c} />
        </aside>
      </div>
      <Tabs items={CASE_TABS} value={tab} onChange={(t) => setParam('tab', t)} label="Case sections" />
      <div role="tabpanel" aria-label={CASE_TABS.find((t) => t.id === tab)!.label} className={styles.panel}>
        {tab === 'overview' ? (
          <ul className={styles.recs}>
            {[
              { id: c.transaction.id, k: 'Card transaction', v: `${c.transaction.merchant} · ${formatMoney(c.transaction.amount_cents, cur)}` },
              { id: c.cardholder.id, k: 'Cardholder', v: `${c.cardholder.name} · ${c.cardholder.contact_on_file.email}` },
            ].map((r) => (
              <li key={r.id}>
                <button type="button" className={sel === r.id ? `${styles.rec} ${styles.recOn}` : styles.rec} aria-pressed={sel === r.id} onClick={() => setParam('sel', sel === r.id ? null : r.id)}>
                  <span className={styles.mono}>{r.id}</span> {r.k} · {r.v}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {tab === 'decision' ? <PolicyBlock c={c} /> : null}
        {tab === 'trace' ? (
          <dl className={styles.kv}>
            <dt>Case version</dt>
            <dd>{c.case_version}</dd>
            <dt>Workflow</dt>
            <dd>v{c.pins.workflow_version}</dd>
            <dt>Policy</dt>
            <dd>v{c.pins.policy_version}</dd>
            <dt>Evidence snapshot</dt>
            <dd className={styles.mono}>{c.pins.evidence_snapshot}</dd>
          </dl>
        ) : null}
      </div>
    </div>
  );
}
