'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useRunCommand, type ActionView, type CaseView } from '@/api';
import { ActionBar } from '@/components/case';
import { ApprovalHistory, DecisionFocus, PacketView } from '@/components/decision';
import { Button } from '@/design-system/primitives';
import { commandForms } from './command-forms';
import type { DecisionPacket } from './contract';
import { decisionPacketQuery, isNotAvailable } from './queries';
import styles from './panel.module.css';

export type DecisionPanelProps = { c: CaseView; selected?: string | null; onSelectRecord?: (recordId: string) => void };

/** Server packet → presentational props. Labels and values are the server's; nothing is computed. */
export function packetProps(p: DecisionPacket, c?: CaseView) {
  const policy = p.policy ?? (c?.policy ? { label: c.policy.label, rules: c.policy.rules_failed.map((label) => ({ label, passed: false, record_ids: c.policy!.evidence_used })) } : null);
  const versions = [`Packet v${p.version}`, p.policy_version != null ? `policy v${p.policy_version}` : null, p.workflow_version != null ? `workflow v${p.workflow_version}` : null]
    .filter(Boolean)
    .join(' · ');
  return { sections: p.sections, refs: p.citations ?? [], policy, versions };
}

/** Analyst Decision tab: decide / waiting on reviewer / returned / stale (prototype focus card for those steps). */
export function DecisionPanel({ c, selected, onSelectRecord }: DecisionPanelProps) {
  const packet = useQuery(decisionPacketQuery(c.case_id));
  const run = useRunCommand(c.case_id);
  const [form, setForm] = useState<ActionView | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const p = packet.data;
  const returned = c.step === 'returned' && p?.return_reason ? [`“${p.return_reason}” Update the rationale and resend.`] : [];
  const act = (a: ActionView) => {
    if (commandForms[a.command]?.length) {
      setForm(a);
      setVals({});
      return;
    }
    run.mutate({ action: a, caseVersion: c.case_version });
  };
  return (
    <DecisionFocus id="task" label="Decision" eyebrow={c.state_label} title={c.next_action} paras={returned}>
      <div data-step={c.step}>
        {packet.isPending ? <p className={styles.rd}>Loading the decision packet…</p> : null}
        {packet.isError ? (
          <p className={styles.rd} data-testid="packet-unavailable">
            {isNotAvailable(packet.error) ? 'Decision packet: not available yet.' : 'The decision packet could not be loaded.'}
          </p>
        ) : null}
        {p ? (
          <>
            <PacketView {...packetProps(p, c)} selected={selected} onSelectRecord={onSelectRecord} />
            <ApprovalHistory items={p.approvals ?? []} />
          </>
        ) : null}
        {form ? (
          <div className={styles.form}>
            {commandForms[form.command]!.map((f) => (
              <label key={f.name} className={styles.field}>
                <span>{f.label}</span>
                {f.multiline ? (
                  <textarea className={styles.ta} value={vals[f.name] ?? ''} onChange={(e) => setVals({ ...vals, [f.name]: e.target.value })} />
                ) : (
                  <input className={styles.in} value={vals[f.name] ?? ''} onChange={(e) => setVals({ ...vals, [f.name]: e.target.value })} />
                )}
              </label>
            ))}
            <div className={styles.acts}>
              <Button
                variant="go"
                disabled={run.isPending || commandForms[form.command]!.some((f) => !(vals[f.name] ?? '').trim())}
                onClick={() => run.mutate({ action: form, caseVersion: c.case_version, payload: vals }, { onSuccess: () => setForm(null) })}
              >
                {form.label}
              </Button>
              <Button variant="ghost" onClick={() => setForm(null)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
        {run.error ? (
          <p className={styles.err} role="alert">
            {run.error.message}
          </p>
        ) : null}
        <ActionBar actions={c.available_actions} blocked={c.blocked_actions} busy={run.isPending ? (run.variables?.action.command ?? '') : null} onAction={act} />
      </div>
    </DecisionFocus>
  );
}
