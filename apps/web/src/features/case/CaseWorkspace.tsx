'use client';

import { useQuery } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { activityQuery, ApiError, evidenceQuery, useCaseView, useMaterialChange, useRunCommand, useSession, usersQuery, type ActionView, type CaseView } from '@/api';
import { ActionBar } from '@/components/case';
import { Banner, Button, Field, SelectField, Skeleton, StatusSlot } from '@/design-system/primitives';
import { actorLabel, dayLabel, formatMoney, roleLabel, sentence } from '@/lib';
import { caseSteps, recoveryActions, slotFor, taskLabel } from './adapters';
import { viewForRole } from '@/features/shell/role-view';
import { pageContextActions, usePageContext } from '@/state';
import { caseRegistry } from './mounts';
import { CASE_TABS, panelsFor, taskBlockFor, type CaseSlotProps, type CaseTabId } from './registry';
import { EvidencePanel } from './EvidencePanel';
import { RunDetails } from './RunDetails';
import styles from './CaseWorkspace.module.css';

export { CASE_TABS };
type TabId = CaseTabId;
const DEFAULT_TAB: TabId = 'decision';
const parseTab = (v: string | null): TabId => (CASE_TABS.some((t) => t.id === v) ? (v as TabId) : DEFAULT_TAB);

// A command blocked only because the case is at another step says nothing useful; real blocks (policy, roles) stay.
// A closed case lists every command as refused for that one reason; the Closed state already says it.
const wrongStep = (b: { label: string; blocked_reason: string }, c: CaseView) => c.state === 'closed' || b.blocked_reason === `${b.label} is not available while the case is '${c.state_label}'.`;
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
            <dd>{p.rules_failed.length ? p.rules_failed.map(sentence).join(' · ') : 'None'}</dd>
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
    { k: 'Posted charge', v: formatMoney(i.posted_cents, cur, 'cents'), cls: '' },
    { k: 'Gross exposure', v: formatMoney(i.exposure_cents, cur, 'cents'), cls: '' },
    { k: 'Temporary credit · pending', v: i.temporary_credit_cents ? formatMoney(i.temporary_credit_cents, cur, 'cents') : '—', cls: '' },
    { k: 'Confirmed recoveries', v: i.confirmed_recovery_cents ? formatMoney(i.confirmed_recovery_cents, cur, 'cents') : '—', cls: '' },
    { k: 'Net exposure', v: formatMoney(i.net_exposure_cents, cur, 'cents'), cls: styles.tot },
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

/** Rows shown before "Show all" (the audit history stays complete on the server). */
const ACTIVITY_SHOWN = 8;

/** Newest first (events in the same instant keep the server's order, latest first), grouped by day (prototype .actv-day). */
function dayGroups<T extends { at: string }>(events: readonly T[]): [string, T[]][] {
  const out: [string, T[]][] = [];
  for (const e of [...events].reverse().sort((a, b) => b.at.localeCompare(a.at))) {
    const d = dayLabel(e.at);
    if (out.length && out[out.length - 1][0] === d) out[out.length - 1][1].push(e);
    else out.push([d, [e]]);
  }
  return out;
}

function Activity({ caseId }: { caseId: string }) {
  const q = useQuery(activityQuery(caseId));
  const [all, setAll] = useState(false);
  // The server scopes activity to staff: a typed 403 hides the section (no client role logic).
  if (q.error instanceof ApiError && q.error.status === 403) return null;
  const events = q.data?.events ?? [];
  const groups = dayGroups(events);
  const limit = all ? Infinity : ACTIVITY_SHOWN;
  let left = limit;
  const shown = groups.map(([day, rows]) => {
    const take = rows.slice(0, Math.max(0, left));
    left -= take.length;
    return [day, take] as const;
  }).filter(([, rows]) => rows.length);
  return (
    <section className={cx(styles.card, styles.actv)} id="activity" aria-labelledby="actv-h">
      <div className={styles.actvH}>
        <h2 className={styles.secT} id="actv-h" style={{ margin: 0 }}>
          Activity
        </h2>
        <span className={styles.actvN}>Audit history · newest first</span>
      </div>
      {q.isPending ? (
        <div className={styles.actvMore} aria-busy="true">
          <Skeleton height={14} width={240} />
        </div>
      ) : q.isError ? (
        <div className={styles.actvDay}>Activity could not be loaded: {q.error.message}</div>
      ) : events.length === 0 ? (
        <div className={styles.actvDay}>No activity yet</div>
      ) : (
        shown.map(([day, rows]) => (
          <div key={day}>
            <div className={styles.actvDay}>{day}</div>
            {rows.map((e) => {
              const who = actorLabel(e.actor_name);
              const role = roleLabel(e.actor_role, e.actor_name);
              return (
                <div key={e.id} className={styles.actvR} data-testid="activity-row">
                  <span className={styles.actvT}>{timeLabel(e.at)}</span>
                  <span className={styles.actvW}>{role ? `${who} · ${role}` : who}</span>
                  <div className={styles.actvA}>
                    <span>{e.summary}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ))
      )}
      {events.length > ACTIVITY_SHOWN ? (
        <div className={styles.actvMore}>
          <button type="button" className={styles.linkb} aria-expanded={all} onClick={() => setAll((x) => !x)}>
            {all ? 'Show recent only' : `Show all ${events.length} events`}
          </button>
        </div>
      ) : null}
    </section>
  );
}

function CommandForm({ action, error, busy, onSubmit, onCancel }: { action: ActionView; error: string | null; busy: boolean; onSubmit: (p: Record<string, unknown>) => void; onCancel: () => void }) {
  const fields = caseRegistry.commandForms[action.command] ?? [];
  const users = useQuery({ ...usersQuery, enabled: fields.some((f) => f.users) });
  const options = (f: (typeof fields)[number]) => (f.targets ? (action.targets ?? []).map((t) => ({ value: t, label: t })) : f.choices);
  // Selects start on the server's payload_default when it is one of the options, else the first option; what the
  // user sees is what is sent.
  const initial = (f: (typeof fields)[number]): [string, string][] => {
    const o = options(f);
    if (!o?.length) return [];
    const d = action.payload_defaults[f.name];
    return [[f.name, o.some((x) => x.value === d) ? String(d) : o[0]!.value]];
  };
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.flatMap(initial)));
  const [checked, setChecked] = useState<Record<string, boolean>>(() => Object.fromEntries(fields.filter((f) => f.checkbox).map((f) => [f.name, false])));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    // Empty inputs are not sent, so the server's payload_defaults (e.g. mode) apply.
    onSubmit({ ...Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== '')), ...checked });
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
        f.checkbox ? (
          <label key={f.name} className={styles.fP} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input type="checkbox" name={f.name} checked={checked[f.name] ?? false} onChange={(e) => setChecked((x) => ({ ...x, [f.name]: e.target.checked }))} />
            {f.label}
          </label>
        ) : options(f) ? (
          <SelectField key={f.name} label={f.label} name={f.name} options={options(f)!} value={values[f.name] ?? ''} error={i === 0 && error ? error : undefined} onChange={(e) => set(f.name, e.target.value)} />
        ) : f.multiline ? (
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
    <section className={styles.progWrap} aria-label="Workflow progress" data-parity="progress">
      <div className={styles.prog}>
        <span>
          {cur ? (
            <>
              Step {curIdx + 1} of {steps.length} · <b style={{ color: '#0c0a08', fontWeight: 550 }}>{cur.label}</b>
            </>
          ) : (
            `All ${steps.length} steps complete`
          )}
        </span>
        <div className={styles.progBar} aria-hidden="true">
          {steps.map((s) => (
            <i key={s.key} className={s.status === 'done' ? styles.done : s.status === 'current' || s.status === 'blocked' ? styles.cur : undefined} />
          ))}
        </div>
        <button type="button" className={styles.linkb} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? 'Hide steps' : 'Show steps'}
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

/** Prototype `.shell > main.main` with the Vera rail as the right-hand column (a drawer below 1280px). */
function Frame({ children, rail = null, busy, step, state }: { children: ReactNode; rail?: ReactNode; busy?: boolean; step?: string; state?: string }) {
  return (
    <div className={styles.shell}>
      <main className={styles.main} aria-busy={busy || undefined}>
        <div className={styles.page} data-step={step} data-state={state}>
          {children}
        </div>
      </main>
      {rail}
    </div>
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
  const { railOpen } = usePageContext();
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
  const role = session.data ? viewForRole(session.data.active_role) : null;
  const railHere = !!caseRegistry.rail?.available(role);
  const title = c ? `${c.case_id} · ${c.transaction.merchant}` : null;
  // The top bar shows this case's title and, for staff, the Vera rail toggle (prototype ctxTitle / .vera-b).
  useEffect(() => pageContextActions.claim(title, railHere), [title, railHere]);
  if (!c) {
    if (view.isError) {
      const e = view.error;
      return (
        <Frame>
          <Banner tone="bad" title={e instanceof ApiError && e.status === 403 ? 'Not available for this role' : 'Could not load the case'}>
            {e.message}
          </Banner>
        </Frame>
      );
    }
    return (
      <Frame busy>
        <div className={styles.loading}>
          <Skeleton height={28} width={320} />
          <Skeleton height={16} width={420} />
          <Skeleton height={64} radius={12} />
          <Skeleton height={240} radius={12} />
        </div>
      </Frame>
    );
  }

  const execute = (action: ActionView, payload?: Record<string, unknown>) => {
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
  const reviewAction = c.available_actions.find((a) => a.command === 'review_related_charge') ?? null;
  const relatedReview = reviewAction
    ? {
        action: reviewAction,
        busy: run.isPending,
        error: null,
        onSubmit: (p: Record<string, unknown>) => execute(reviewAction, p),
      }
    : null;

  const cur = c.transaction.currency;
  const recovery = recoveryActions(c);
  const synthetic = session.data?.environment === 'synthetic';
  // Mounted blocks and the Decision tab see the same pruned blocked list as the ActionBar.
  const cv: CaseView = { ...c, blocked_actions: c.blocked_actions.filter((x) => !wrongStep(x, c)) };
  const slot: CaseSlotProps = { caseId, c: cv, role, sel, onSelectRecord: selectRecord };
  const block = taskBlockFor(caseRegistry, c, role);
  const mounted = panelsFor(caseRegistry, tab);
  const hidden = block?.hides?.(c) ?? [];
  const rail = caseRegistry.rail;
  return (
    <Frame step={c.step} state={c.state} rail={rail ? <rail.Rail {...slot} open={railOpen} onClose={() => pageContextActions.setRailOpen(false)} onNavigate={(t) => setParams({ tab: parseTab(t), sel: null })} /> : null}>
      {view.isError ? <Banner tone="warn">Could not refresh: {view.error.message} Showing the last loaded version.</Banner> : null}
      <div className={styles.chd} data-parity="case-header">
        <div>
          <div className={styles.chdT} data-parity="case-amount">{formatMoney(c.transaction.amount_cents, cur, 'cents')}</div>
          <div className={styles.chdM}>
            Card ending {c.transaction.card_last4} · Posted {dateLabel(c.transaction.posted_at)} · {c.cardholder.name}
          </div>
          <div className={styles.chdW}>
            {internalDenied || evidence.isPending ? null : (
              <button type="button" className={styles.linkb} onClick={() => setParams({ tab: 'trace', sel: null })}>
                Workflow v{c.pins.workflow_version} · Run details
              </button>
            )}
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
{block?.ownsTitle ? null : (
                <h2 className={styles.fTitle} data-testid="next-action">
                  {c.next_action}
                </h2>
              )}
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
                <ActionBar actions={c.available_actions.filter((x) => !hidden.includes(x.command))} blocked={c.blocked_actions.filter((x) => !hidden.includes(x.command) && !wrongStep(x, c))} busy={run.isPending ? (run.variables?.action.command ?? null) : null} onAction={onAction} />
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
            <div className={styles.tabs} role="tablist" aria-label="Case sections" data-parity="case-tabs">
              {tabs.map((t) => (
                <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={cx(styles.tab, tab === t.id && styles.on)} onClick={() => setParams({ tab: t.id, sel: null })}>
                  {t.label}
                </button>
              ))}
            </div>
            <div role="tabpanel" aria-label={CASE_TABS.find((t) => t.id === tab)!.label}>
              {tab === 'evidence' ? <EvidencePanel caseId={caseId} sel={sel} onSelect={selectRecord} review={relatedReview} /> : null}
              {tab === 'comms' && !mounted.length ? (
                <div className={styles.inspBody} data-testid="slot-empty-comms">
                  <div className={styles.lbl}>Messages and calls</div>
                  <p className={styles.rd}>Not available yet.</p>
                </div>
              ) : null}
              {/* The policy block always shows; a mounted decision packet stacks below it. */}
              {tab === 'decision' ? <DecisionPanel c={cv} /> : null}
              {tab === 'trace' ? <RunDetails c={c} ev={evidence.data} recovery={recovery} onRecovery={onAction} /> : null}
              {tab === 'comms' && mounted.length ? (
                <div className={styles.inspBody}>
                  {mounted.map((m) => (
                    <div key={m.key} data-testid={`tab-panel-${m.key}`}>
                      <m.Panel {...slot} />
                    </div>
                  ))}
                </div>
              ) : (
                mounted.map((m) => (
                  <div key={m.key} data-testid={`tab-panel-${m.key}`}>
                    <m.Panel {...slot} />
                  </div>
                ))
              )}
            </div>
          </section>
          )}
        </div>
      </div>
    </Frame>
  );
}
