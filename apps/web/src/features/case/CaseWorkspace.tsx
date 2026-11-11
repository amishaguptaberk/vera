'use client';

import { useQuery } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { activityQuery, ApiError, evidenceQuery, useCaseView, useMaterialChange, useRunCommand, useSession, usersQuery, type ActionView, type CaseView } from '@/api';
import { ActionBar } from '@/components/case';
import { Banner, Button, Field, Skeleton, StatusSlot } from '@/design-system/primitives';
import { formatMoney } from '@/lib';
import { caseSteps, recoveryActions, slotFor, taskLabel } from './adapters';
import { viewForRole } from '@/features/shell/role-view';
import { caseRegistry } from './mounts';
import { CASE_TABS, panelsFor, taskBlockFor, type CaseSlotProps, type CaseTabId } from './registry';
import { EvidencePanel } from './EvidencePanel';
import { RunDetails } from './RunDetails';
import styles from './CaseWorkspace.module.css';

export { CASE_TABS };
type TabId = CaseTabId;
const DEFAULT_TAB: TabId = 'decision';
const parseTab = (v: string | null): TabId => (CASE_TABS.some((t) => t.id === v) ? (v as TabId) : DEFAULT_TAB);

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');
const dateLabel = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
const timeLabel = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

function DecisionPanel({ c }: { c: CaseView }) {
  const p = c.policy;
  return (
    <div className={styles.inspBody} data-testid="policy-block">
      <div className={styles.lbl}>Recommendation</div>
      <div className={styles.rec}>{c.next_action}</div>
      <div className={styles.lbl} style={{ marginTop: 12 }}>
        Policy
      </div>
      {!p ? (
        <div className={styles.rd} style={{ color: '#3b3a39' }}>
          Not evaluated yet
        </div>
      ) : (
        <>
          <div className={styles.rd} style={{ color: '#3b3a39' }}>
            {p.label} · v{p.policy_version}
          </div>
          <dl className={styles.kvl} style={{ marginTop: 8 }}>
            <dt>Status</dt>
            <dd data-testid="policy-status">{p.status}</dd>
            <dt>Rules failed</dt>
            <dd>{p.rules_failed.length ? p.rules_failed.join(', ') : 'None'}</dd>
            <dt>Evidence used</dt>
            <dd>{p.evidence_used.length ? p.evidence_used.join(', ') : 'None'}</dd>
          </dl>
        </>
      )}
      {c.blocked_actions.length ? (
        <div className={styles.dnext}>
          {c.blocked_actions.map((b) => (
            <p key={b.command} className={styles.whyOff} style={{ margin: '0 0 8px' }}>
              <b style={{ color: '#3b3a39', fontWeight: 550 }}>{b.label}</b> · {b.blocked_reason}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ChargeImpact({ c }: { c: CaseView }) {
  const cur = c.transaction.currency;
  const i = c.charge_impact;
  // Every amount is the server's; the client never subtracts.
  const rows = [
    { k: 'Posted charge', v: formatMoney(i.posted_cents, cur), cls: '' },
    { k: 'Gross exposure', v: formatMoney(i.exposure_cents, cur), cls: '' },
    { k: 'Temporary credit · pending', v: i.temporary_credit_cents ? formatMoney(i.temporary_credit_cents, cur) : '—', cls: '' },
    { k: 'Confirmed recoveries', v: i.confirmed_recovery_cents ? formatMoney(i.confirmed_recovery_cents, cur) : '—', cls: '' },
    { k: 'Net exposure', v: formatMoney(i.net_exposure_cents, cur), cls: styles.tot },
  ];
  return (
    <section className={styles.plainSec} aria-labelledby="ci-h" data-parity="charge-impact">
      <div className={styles.secRow}>
        <h2 className={styles.secT} id="ci-h" style={{ margin: 0 }}>
          Charge impact
        </h2>
        <span className={styles.simnote}>No funds moved</span>
      </div>
      <table className={styles.ledger}>
        <tbody>
          {rows.map((r) => (
            <tr key={r.k} className={r.cls || undefined}>
              <td>{r.k}</td>
              <td>{r.v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {i.note ? (
        <p className={styles.whyOff} style={{ marginTop: 10 }}>
          {i.note}
        </p>
      ) : null}
    </section>
  );
}

function Activity({ caseId }: { caseId: string }) {
  const q = useQuery(activityQuery(caseId));
  // The server scopes activity to staff: a typed 403 hides the section (no client role logic).
  if (q.error instanceof ApiError && q.error.status === 403) return null;
  const events = q.data?.events ?? [];
  return (
    <section className={cx(styles.card, styles.actv)} id="activity" aria-labelledby="actv-h">
      <div className={styles.actvH}>
        <h2 className={styles.secT} id="actv-h" style={{ margin: 0 }}>
          Activity
        </h2>
        <span className={styles.actvN}>Audit history · newest first</span>
      </div>
      {events.length === 0 ? (
        <div className={styles.actvDay}>No activity yet</div>
      ) : (
        [...events]
          .sort((a, b) => b.at.localeCompare(a.at))
          .map((e) => (
            <div key={e.id} className={styles.actvR} data-testid="activity-row">
              <span className={styles.actvT}>{timeLabel(e.at)}</span>
              <span className={styles.actvW}>
                {e.actor_name} · {e.actor_role.replace(/_/g, ' ')}
              </span>
              <div className={styles.actvA}>
                <span>{e.summary}</span>
              </div>
            </div>
          ))
      )}
    </section>
  );
}

function CommandForm({ action, error, busy, onSubmit, onCancel }: { action: ActionView; error: string | null; busy: boolean; onSubmit: (p: Record<string, string>) => void; onCancel: () => void }) {
  const fields = caseRegistry.commandForms[action.command] ?? [];
  const users = useQuery({ ...usersQuery, enabled: fields.some((f) => f.users) });
  const [values, setValues] = useState<Record<string, string>>({});
  const submit = (e: FormEvent) => {
    e.preventDefault();
    // Empty inputs are not sent, so the server's payload_defaults (e.g. mode) apply.
    onSubmit(Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== '')));
  };
  const set = (name: string, v: string) => setValues((x) => ({ ...x, [name]: v }));
  return (
    <form className={styles.form} onSubmit={submit} aria-label={action.label}>
      {action.confirm ? <p className={styles.fP}>{action.confirm}</p> : null}
      {users.data?.users?.length ? (
        <datalist id="vera-users">
          {(users.data?.users ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </datalist>
      ) : null}
      {fields.map((f, i) =>
        f.multiline ? (
          <Field key={f.name} multiline label={f.label} name={f.name} rows={2} value={values[f.name] ?? ''} error={i === 0 && error ? error : undefined} onChange={(e) => set(f.name, e.target.value)} />
        ) : (
          <Field key={f.name} label={f.label} name={f.name} placeholder={f.placeholder} list={f.users && users.data?.users?.length ? 'vera-users' : undefined} value={values[f.name] ?? ''} error={i === 0 && error ? error : undefined} onChange={(e) => set(f.name, e.target.value)} />
        ),
      )}
      <div className={styles.acts}>
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

function Progress({ c }: { c: CaseView }) {
  const [open, setOpen] = useState(false);
  const steps = caseSteps(c);
  if (!steps) {
    return (
      <section className={styles.progWrap} aria-label="Workflow progress">
        <div className={styles.prog}>
          <span>Workflow steps not available yet</span>
        </div>
      </section>
    );
  }
  const curIdx = steps.findIndex((s) => s.status === 'current' || s.status === 'blocked');
  const cur = curIdx >= 0 ? steps[curIdx] : null;
  return (
    <section className={styles.progWrap} aria-label="Workflow progress">
      <div className={styles.prog}>
        <span>
          Step {curIdx + 1} of {steps.length} · <b style={{ color: '#0c0a08', fontWeight: 550 }}>{cur?.label ?? ''}</b>
        </span>
        <div className={styles.progBar} aria-hidden="true">
          {steps.map((s) => (
            <i key={s.key} className={s.status === 'done' ? styles.done : s.status === 'current' || s.status === 'blocked' ? styles.cur : undefined} />
          ))}
        </div>
        <button type="button" className={styles.linkb} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? 'Hide steps' : 'Show all steps'}
        </button>
      </div>
      {open ? (
        <ol className={styles.stepsL}>
          {steps.map((s, i) => (
            <li key={s.key} className={s.status === 'done' ? styles.done : s.status === 'current' || s.status === 'blocked' ? styles.cur : undefined}>
              <span className={styles.n}>{i + 1}</span>
              <span>{s.label}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

export function CaseWorkspace({ caseId }: { caseId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requestedTab = parseTab(params.get('tab'));
  const sel = params.get('sel');
  const view = useCaseView(caseId);
  const session = useSession();
  const evidence = useQuery(evidenceQuery(caseId));
  const run = useRunCommand(caseId);
  const material = useMaterialChange(caseId);
  // The server scopes internal reads (evidence, runs, activity) to staff. A 403 on the evidence read drops the
  // internal tabs (Evidence, Decision with its policy evidence ids, Run details); no client-side role logic.
  const internalDenied = evidence.error instanceof ApiError && evidence.error.status === 403;
  const tabs = internalDenied ? CASE_TABS.filter((t) => t.id === 'comms') : CASE_TABS;
  const tab: TabId = tabs.some((t) => t.id === requestedTab) ? requestedTab : tabs[0].id;
  const [railOpen, setRailOpen] = useState(false);
  const [formFor, setFormFor] = useState<ActionView | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'warn' | 'bad'; text: string } | null>(null);

  const setParams = (patch: Partial<Record<'tab' | 'sel', string | null>>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === undefined) next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const c = view.data;
  if (!c) {
    if (view.isError) {
      const e = view.error;
      return (
        <div className={styles.page}>
          <Banner tone="bad" title={e instanceof ApiError && e.status === 403 ? 'Not available for this role' : 'Could not load the case'}>
            {e.message}
          </Banner>
        </div>
      );
    }
    return (
      <div className={styles.page} aria-busy="true">
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
    if (caseRegistry.commandForms[a.command]) {
      setFormError(null);
      setFormFor(a);
    } else execute(a);
  };
  const selectRecord = (id: string | null) => setParams({ tab: 'evidence', sel: id });

  const cur = c.transaction.currency;
  const recovery = recoveryActions(c);
  const synthetic = session.data?.environment === 'synthetic';
  const role = session.data ? viewForRole(session.data.active_role) : null;
  const slot: CaseSlotProps = { caseId, c, role, sel, onSelectRecord: selectRecord };
  const block = taskBlockFor(caseRegistry, c, role);
  const mounted = panelsFor(caseRegistry, tab);
  const hidden = block?.hides?.(c) ?? [];
  const rail = caseRegistry.rail;
  return (
    <div className={styles.page} data-step={c.step} data-state={c.state}>
      {view.isError ? <Banner tone="warn">Could not refresh: {view.error.message} Showing the last loaded version.</Banner> : null}
      <div className={styles.chd} data-parity="case-header">
        <div>
          <div className={styles.chdT}>{formatMoney(c.transaction.amount_cents, cur, 'cents')}</div>
          <div className={styles.chdM}>
            Card ending {c.transaction.card_last4} · Posted {dateLabel(c.transaction.posted_at)} · {c.cardholder.name}
          </div>
          <div className={styles.chdW}>
            {internalDenied || evidence.isPending ? null : (
              <button type="button" className={styles.linkb} onClick={() => setParams({ tab: 'trace', sel: null })}>
                Workflow v{c.pins.workflow_version} · Run details
              </button>
            )}
            {rail ? <rail.Toggle role={role} open={railOpen} onToggle={() => setRailOpen((o) => !o)} /> : null}
          </div>
        </div>
        <dl className={styles.cstate} aria-label="Case status" style={{ margin: 0 }}>
          <div>
            <dt className={styles.k}>Current state</dt>
            <dd className={cx(styles.v, styles.now)} style={{ margin: 0 }}>
              <StatusSlot state={slotFor(c.state_kind)} />
              <span data-testid="case-state">{c.state_label}</span>
            </dd>
          </div>
          <div>
            <dt className={styles.k}>Next action</dt>
            <dd className={styles.v} style={{ margin: 0 }}>
              {c.next_action}
            </dd>
          </div>
          <div>
            <dt className={styles.k}>Owner</dt>
            <dd className={styles.v} style={{ margin: 0 }}>
              {c.owner.name}
            </dd>
          </div>
          <div>
            <dt className={styles.k}>Due</dt>
            <dd className={cx(styles.v, c.due?.overdue && styles.dueOver)} style={{ margin: 0 }}>
              {c.due?.label ?? 'No deadline'}
            </dd>
          </div>
        </dl>
      </div>
      <Progress c={c} />
      <div className={styles.caseMain}>
        <div className={styles.colM}>
          <section className={styles.focus} id="task" data-parity="task" aria-label="Current task" aria-live="polite">
            <div className={styles.focusIn}>
              <div className={styles.fState}>
                <span>{taskLabel(c.state_kind)}</span>
              </div>
              <h2 className={styles.fTitle} data-testid="next-action">
                {c.next_action}
              </h2>
              {c.hold ? (
                <p className={styles.fP} data-testid="hold-info">
                  On hold: {c.hold.reason}
                </p>
              ) : null}
              {notice ? <Banner tone={notice.tone}>{notice.text}</Banner> : null}
              {block ? (
                <div data-testid={`task-block-${block.key}`}>
                  <block.Block {...slot} />
                </div>
              ) : null}
              {formFor ? (
                <CommandForm key={formFor.command} action={formFor} error={formError} busy={run.isPending} onSubmit={(p) => execute(formFor, p)} onCancel={() => setFormFor(null)} />
              ) : block?.ownsActions ? null : (
                <ActionBar actions={c.available_actions.filter((x) => !hidden.includes(x.command))} blocked={c.blocked_actions.filter((x) => !hidden.includes(x.command))} busy={run.isPending ? (run.variables?.action.command ?? null) : null} onAction={onAction} />
              )}
              {synthetic ? (
                <details className={styles.demoD}>
                  <summary>Demo controls</summary>
                  <div className={styles.demoRow}>
                    <Button variant={['sm', 'demo']} disabled={material.isPending} onClick={() => material.mutate()}>
                      Simulate material change
                    </Button>
                    {material.data ? (
                      <span>
                        New version v{material.data.version}
                        {material.data.stale_checks.length ? ` · stale checks: ${material.data.stale_checks.join(', ')}` : ''}
                      </span>
                    ) : null}
                    {material.isError ? <span>{material.error.message}</span> : null}
                  </div>
                </details>
              ) : null}
            </div>
          </section>
          <ChargeImpact c={c} />
          <Activity caseId={caseId} />
        </div>
        <div className={styles.colR}>
          {/* Every tab reads internal data (evidence, messages, verification, runs); a server 403 drops the card. */}
          {internalDenied || evidence.isPending ? null : (
          <section className={styles.card} aria-label="Case workspace">
            <div className={styles.tabs} role="tablist" aria-label="Case sections">
              {tabs.map((t) => (
                <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={cx(styles.tab, tab === t.id && styles.on)} onClick={() => setParams({ tab: t.id, sel: null })}>
                  {t.label}
                </button>
              ))}
            </div>
            <div role="tabpanel" aria-label={CASE_TABS.find((t) => t.id === tab)!.label}>
              {tab === 'evidence' ? <EvidencePanel caseId={caseId} sel={sel} onSelect={selectRecord} /> : null}
              {tab === 'comms' && !mounted.length ? (
                <div className={styles.inspBody} data-testid="slot-empty-comms">
                  <div className={styles.lbl}>Messages and calls</div>
                  <p className={styles.rd}>Not available yet.</p>
                </div>
              ) : null}
              {/* The policy block always shows; a mounted decision packet stacks below it. */}
              {tab === 'decision' ? <DecisionPanel c={c} /> : null}
              {tab === 'trace' ? <RunDetails c={c} ev={evidence.data} recovery={recovery} onRecovery={onAction} /> : null}
              {mounted.map((m) => (
                <div key={m.key} data-testid={`tab-panel-${m.key}`}>
                  <m.Panel {...slot} />
                </div>
              ))}
            </div>
          </section>
          )}
        </div>
      </div>
      {rail ? <rail.Rail {...slot} open={railOpen} onClose={() => setRailOpen(false)} onNavigate={(t) => setParams({ tab: parseTab(t), sel: null })} /> : null}
    </div>
  );
}
