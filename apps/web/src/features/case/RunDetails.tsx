'use client';

import { useQuery } from '@tanstack/react-query';
import { runsQuery, type ActionView, type CaseView, type EvidenceRegister, type RunOut } from '@/api';
import { ActionBar } from '@/components/case';
import { Skeleton, StatusSlot } from '@/design-system/primitives';
import { actorLabel } from '@/lib';
import { stepLabels } from './adapters';
import styles from './CaseWorkspace.module.css';

const usage = (u: Record<string, unknown>) =>
  Object.entries(u)
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
    .join(' · ') || '—';

const at = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : null);

/** Prototype trace entries (`.tr`): one per specialist step, newest run first. Values are the server's. */
export function RunList({ runs, recovery, onRecovery }: { runs: readonly RunOut[]; recovery: readonly ActionView[]; onRecovery: (a: ActionView) => void }) {
  if (!runs.length) return <p className={styles.rd}>No specialist runs yet.</p>;
  return (
    <>
      {[...runs].reverse().map((r) => (
        <div key={r.id} className={styles.run} data-testid="run">
          <div className={styles.runH}>
            Run {r.id} · {r.status} · {r.mode.toUpperCase()} · workflow v{r.workflow_version} · policy v{r.policy_version}
          </div>
          <ol className={styles.seq} aria-label="Run sequence">
            {r.steps.map((s) => {
              const l = stepLabels(s);
              const rec = recovery.filter((a) => a.payload_defaults?.step_key === s.step_key);
              const when = at(s.finished_at ?? s.started_at);
              return (
                <li key={s.step_key} className={styles.tr} data-testid={`step-${s.step_key}`}>
                  <div className={styles.trH}>
                    <span className={styles.trN}>
                      <StatusSlot state={l.slot} label={s.status} />
                      {actorLabel(s.specialist)}
                      {l.mode ? <span className={styles.modeTag}>{l.mode}</span> : null}
                      {l.replayed ? <span className={styles.modeTag}>Replayed result</span> : null}
                    </span>
                    <span className={styles.trT}>{when ? `${s.step_key} · ${when}` : s.step_key}</span>
                  </div>
                  <dl className={styles.trL}>
                    <dt>Status</dt>
                    <dd>{s.status}</dd>
                    <dt>Model</dt>
                    <dd>
                      <span className={styles.mono}>{s.model_id ?? '—'}</span>
                    </dd>
                    {s.execution_mode === 'replay' ? (
                      <>
                        <dt>Execution</dt>
                        <dd>Reference recording (not a live model)</dd>
                      </>
                    ) : null}
                    <dt>Prompt</dt>
                    <dd>{s.prompt_version ?? '—'}</dd>
                    <dt>Tokens</dt>
                    <dd>{usage(s.usage)}</dd>
                    <dt>Attempts</dt>
                    <dd>{s.attempts}</dd>
                    {s.failure_reason ? (
                      <>
                        <dt>Failure</dt>
                        <dd className={styles.failure}>{s.failure_reason}</dd>
                      </>
                    ) : null}
                  </dl>
                  {s.status === 'failed' && rec.length ? <ActionBar actions={rec} blocked={[]} onAction={onRecovery} /> : null}
                </li>
              );
            })}
          </ol>
        </div>
      ))}
    </>
  );
}

export function RunDetails({ c, ev, recovery, onRecovery }: { c: CaseView; ev: EvidenceRegister | undefined; recovery: readonly ActionView[]; onRecovery: (a: ActionView) => void }) {
  const runs = useQuery(runsQuery(c.case_id));
  const latest = runs.data?.length ? runs.data[runs.data.length - 1] : null;
  return (
    <div className={styles.inspBody} data-testid="run-details">
      <dl className={styles.kvl} style={{ marginBottom: 14 }}>
        <dt>Workflow version</dt>
        <dd>v{c.pins.workflow_version}</dd>
        <dt>Policy version</dt>
        <dd>v{c.pins.policy_version}</dd>
        <dt>Evidence snapshot</dt>
        <dd className={styles.mono}>{ev?.snapshot_hash ?? c.pins.evidence_snapshot}</dd>
        <dt>Case version</dt>
        <dd>v{c.case_version} · append-only history</dd>
        {latest ? (
          <>
            <dt>Run ID</dt>
            <dd className={styles.mono}>{latest.id}</dd>
          </>
        ) : null}
        {c.policy ? (
          <>
            <dt>Last policy evaluation</dt>
            <dd>
              {c.policy.label} · v{c.policy.policy_version}
            </dd>
          </>
        ) : null}
      </dl>
      <div className={styles.evg}>Execution trace</div>
      <p className={styles.fine}>Specialist runs and their steps, newest run first.</p>
      {runs.data ? (
        <RunList runs={runs.data} recovery={recovery} onRecovery={onRecovery} />
      ) : runs.isError ? (
        <p className={styles.rd}>{runs.error.message}</p>
      ) : (
        <div aria-busy="true" className={styles.loading}>
          <Skeleton height={14} width={220} />
          <Skeleton height={64} />
        </div>
      )}
    </div>
  );
}
