'use client';

import { useQuery } from '@tanstack/react-query';
import { runsQuery, type ActionView, type CaseView, type EvidenceRegister, type RunOut } from '@/api';
import { ActionBar } from '@/components/case';
import { StatusSlot } from '@/design-system/primitives';
import { AUTHORED_REFERENCE, stepLabels } from './adapters';
import styles from './CaseWorkspace.module.css';

const usage = (u: Record<string, unknown>) =>
  Object.entries(u)
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
    .join(' · ') || '—';

export function RunList({ runs, recovery, onRecovery }: { runs: readonly RunOut[]; recovery: readonly ActionView[]; onRecovery: (a: ActionView) => void }) {
  if (!runs.length) return <p className={styles.rd}>No specialist runs yet.</p>;
  return (
    <>
      {runs.map((r) => (
        <div key={r.id} className={styles.run} data-testid="run">
          <div className={styles.evg}>
            Run {r.id} · {r.status} · {r.mode.toUpperCase()} · workflow v{r.workflow_version} · policy v{r.policy_version}
          </div>
          <ol className={styles.seq} aria-label="Run sequence">
            {r.steps.map((s) => {
              const l = stepLabels(s);
              const rec = recovery.filter((a) => a.payload_defaults?.step_key === s.step_key);
              return (
                <li key={s.step_key} className={styles.seqRow} data-testid={`step-${s.step_key}`}>
                  <div className={styles.seqHead}>
                    <StatusSlot state={l.slot} label={s.status} />
                    <span className={styles.seqN}>{s.specialist}</span>
                    <span className={styles.seqA}>· {s.step_key}</span>
                    {l.mode ? <span className={styles.modeTag}>{l.mode}</span> : null}
                    {l.replayed ? <span className={styles.modeTag}>Replayed result</span> : null}
                  </div>
                  <dl className={styles.kvl}>
                    <dt>Status</dt>
                    <dd>{s.status}</dd>
                    <dt>Model</dt>
                    <dd>
                      {s.model_id ?? '—'}
                      {s.model_id === AUTHORED_REFERENCE ? ' · reference recording (not a live model)' : ''}
                    </dd>
                    <dt>Prompt version</dt>
                    <dd>{s.prompt_version ?? '—'}</dd>
                    <dt>Token usage</dt>
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
  return (
    <div className={styles.inspBody} data-testid="run-details">
      <dl className={styles.kvl}>
        <dt>Case version</dt>
        <dd>{c.case_version}</dd>
        <dt>Workflow</dt>
        <dd>v{c.pins.workflow_version}</dd>
        <dt>Policy</dt>
        <dd>v{c.pins.policy_version}</dd>
        <dt>Evidence snapshot</dt>
        <dd className={styles.mono}>{ev?.snapshot_hash ?? c.pins.evidence_snapshot}</dd>
      </dl>
      <div className={styles.evg}>Execution trace</div>
      {runs.data ? <RunList runs={runs.data} recovery={recovery} onRecovery={onRecovery} /> : <p className={styles.rd}>{runs.isError ? runs.error.message : 'Loading runs…'}</p>}
    </div>
  );
}
