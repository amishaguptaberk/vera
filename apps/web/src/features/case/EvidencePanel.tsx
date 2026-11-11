'use client';

import { useQuery } from '@tanstack/react-query';
import { evidenceQuery, evidenceRecordQuery, type EvidenceRegister, type FindingView } from '@/api';
import { Skeleton } from '@/design-system/primitives';
import styles from './CaseWorkspace.module.css';

const STATUS_LABEL: Record<string, string> = {
  supporting: 'Supporting',
  missing: 'Missing',
  conflicting: 'Conflicting',
  superseded: 'Superseded',
  pending_review: 'Pending review',
  not_relevant: 'Not relevant',
};
const KIND_LABEL = (k: string) => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

// Groups follow the prototype's evidence register: records by role in the case.
const GROUPS: readonly (readonly [string, (kind: string) => boolean])[] = [
  ['Charge and report', (k) => k === 'charge' || k === 'initial_report' || k === 'cardholder_profile'],
  ['Purchase and delivery', (k) => k === 'purchase_order' || k === 'delivery_record' || k === 'receipt' || k === 'order_confirmation'],
  ['Related charges', (k) => k === 'related_charge'],
];

export type Citation = { record_id: string; version: number | null; field: string | null };
export function citations(f: FindingView): Citation[] {
  return f.links
    .map((l) => ({
      record_id: typeof l.record_id === 'string' ? l.record_id : '',
      version: typeof l.version === 'number' ? l.version : null,
      field: typeof l.field === 'string' ? l.field : null,
    }))
    .filter((c) => c.record_id);
}

const fmtVal = (v: unknown) => (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v));

function RecordView({ caseId, recordId, onBack, onSelect }: { caseId: string; recordId: string; onBack: () => void; onSelect: (id: string) => void }) {
  const q = useQuery(evidenceRecordQuery(caseId, recordId));
  const r = q.data;
  return (
    <div className={styles.inspBody} data-testid="record-view">
      <button type="button" className={styles.backBtn} onClick={onBack}>
        ← Evidence
      </button>
      {!r ? (
        q.isError ? <p className={styles.rd}>{q.error.message}</p> : <Skeleton height={80} />
      ) : (
        <>
          <div className={styles.lbl} style={{ marginTop: 6 }}>
            Source record · {KIND_LABEL(r.kind)}
          </div>
          <div className={styles.it}>
            {r.record_id} <span className={styles.ver}>v{r.current_version}</span>
          </div>
          <div className={styles.isrc}>
            <span className={`${styles.est} ${styles[`est_${r.status}`] ?? ''}`}>{STATUS_LABEL[r.status] ?? r.status}</span>
          </div>
          {[...r.versions]
            .sort((a, b) => b.version - a.version)
            .map((v) => (
              <div key={v.version} className={v.version === r.current_version ? styles.verBlock : `${styles.verBlock} ${styles.superseded}`} data-testid={`version-${v.version}`}>
                <div className={styles.evg}>
                  Version {v.version}
                  {v.version === r.current_version ? ' · current' : ' · superseded'} · {v.source}
                </div>
                <dl className={styles.fields}>
                  {Object.entries(v.fields).map(([k, val]) => (
                    <div key={k} className={styles.fld}>
                      <dt>{k}</dt>
                      <dd>{fmtVal(val)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          {r.findings.length ? (
            <>
              <div className={styles.evg}>Findings citing this record</div>
              <Findings findings={r.findings} onSelect={onSelect} />
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

function Findings({ findings, onSelect }: { findings: readonly FindingView[]; onSelect: (id: string) => void }) {
  return (
    <ul className={styles.findings} aria-label="Findings">
      {findings.map((f) => (
        <li key={f.finding_id} className={styles.finding} data-kind="finding">
          <div className={styles.findingT}>
            <span className={styles.findingTag}>Finding</span> {f.statement}
          </div>
          <div className={styles.cites}>
            {citations(f).map((c, i) => (
              <button key={i} type="button" className={styles.ref} onClick={() => onSelect(c.record_id)}>
                {c.record_id}
                {c.version !== null ? ` · v${c.version}` : ''}
                {c.field ? ` · ${c.field}` : ''}
              </button>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function EvidenceRegisterView({ ev, onSelect }: { ev: EvidenceRegister; onSelect: (id: string) => void }) {
  const placed = new Set<string>();
  const groups = GROUPS.map(([label, match]) => {
    const rows = ev.records.filter((r) => match(r.kind));
    rows.forEach((r) => placed.add(r.record_id));
    return { label, rows };
  });
  const other = ev.records.filter((r) => !placed.has(r.record_id));
  if (other.length) groups.push({ label: 'Other records', rows: other });
  return (
    <div className={styles.inspBody} data-testid="evidence-register">
      {groups
        .filter((g) => g.rows.length)
        .map((g) => (
          <div key={g.label}>
            <div className={styles.evg}>{g.label}</div>
            <table className={styles.evt}>
              <thead>
                <tr>
                  <th scope="col">Record</th>
                  <th scope="col">Version</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {g.rows.map((r) => (
                  <tr key={r.record_id} data-status={r.status} data-kind="record">
                    <td>
                      <button type="button" className={styles.rn} onClick={() => onSelect(r.record_id)}>
                        {r.record_id}
                      </button>
                      <div className={styles.s2}>{KIND_LABEL(r.kind)}</div>
                    </td>
                    <td className={styles.num}>v{r.current_version}</td>
                    <td>
                      <span className={`${styles.est} ${styles[`est_${r.status}`] ?? ''}`}>{STATUS_LABEL[r.status] ?? r.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      {ev.missing.length ? (
        <>
          <div className={styles.evg}>Missing</div>
          <ul className={styles.missing} aria-label="Missing evidence">
            {ev.missing.map((m) => (
              <li key={m} data-status="missing">
                <span className={`${styles.est} ${styles.est_missing}`}>Missing</span> {KIND_LABEL(m)}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {ev.open_conflicts.length ? (
        <>
          <div className={styles.evg}>Open conflicts</div>
          <ul className={styles.missing} aria-label="Open conflicts">
            {ev.open_conflicts.map((c) => (
              <li key={c.finding_id} data-status="conflicting">
                <span className={`${styles.est} ${styles.est_conflicting}`}>Conflicting</span> {c.field}:{' '}
                {c.values.map((v, i) => (
                  <button key={i} type="button" className={styles.ref} onClick={() => onSelect(v.record_id)}>
                    {v.record_id} · v{v.version} · {fmtVal(v.value)}
                  </button>
                ))}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <div className={styles.evg}>Findings</div>
      {ev.findings.length ? <Findings findings={ev.findings} onSelect={onSelect} /> : <p className={styles.rd}>No findings yet.</p>}
    </div>
  );
}

export function EvidencePanel({ caseId, sel, onSelect }: { caseId: string; sel: string | null; onSelect: (id: string | null) => void }) {
  const q = useQuery(evidenceQuery(caseId));
  if (sel) return <RecordView caseId={caseId} recordId={sel} onBack={() => onSelect(null)} onSelect={onSelect} />;
  if (!q.data) return <div className={styles.inspBody}>{q.isError ? <p className={styles.rd}>{q.error.message}</p> : <Skeleton height={120} />}</div>;
  return <EvidenceRegisterView ev={q.data} onSelect={onSelect} />;
}
