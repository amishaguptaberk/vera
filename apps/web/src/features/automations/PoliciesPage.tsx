'use client';

import { useState } from 'react';
import { PoliciesView, type PolicyRuleRow } from '@/components/automations/PoliciesView';
import { isNotAvailable, useAutomationCommand, usePolicy } from './api';
import { POLICY_ID, type PolicyDetail } from './contract';

const EFFECT: Record<string, string> = { ineligible: 'Not eligible for credit', blocked: 'Blocks the case', needs_evidence: 'Requests evidence' };

/** Group server rules by their `group` field, in server order. */
export function policyGroups(detail: PolicyDetail | undefined) {
  const groups: { label: string; rules: PolicyRuleRow[] }[] = [];
  for (const r of detail?.rules ?? []) {
    let g = groups.find((x) => x.label === r.group);
    if (!g) groups.push((g = { label: r.group, rules: [] }));
    g.rules.push({ id: r.id, rule: r.label, ev: r.predicate.replace(/_/g, ' '), eff: EFFECT[r.effect] ?? r.effect, ex: r.code });
  }
  return groups;
}

export function PoliciesPage({ policyId = POLICY_ID }: { policyId?: string }) {
  const [version, setVersion] = useState<number | null>(null);
  const [threshold, setThreshold] = useState('');
  const q = usePolicy(policyId, version);
  const cmd = useAutomationCommand();
  const d = q.data;
  const notice = q.isPending ? 'Loading policy…' : q.isError ? (isNotAvailable(q.error) ? 'Not available yet' : (q.error as Error).message) : null;
  const latest = d ? Math.max(...d.versions) : null;
  const publish = d?.available_actions?.find((a) => a.command === 'publish_policy_version');
  const createDraft = d?.available_actions?.find((a) => a.command === 'create_policy_draft');
  return (
    <PoliciesView
      notice={notice}
      title="Card charge investigation policy"
      sub={d ? `v${d.version}${d.version === latest ? ' · Active' : ' · read-only'}` : ''}
      acts={[
        ...(d?.versions ?? []).map((v) => ({ key: `v${v}`, label: `v${v}`, on: v === d?.version, onClick: () => setVersion(v) })),
        ...(createDraft ? [{ key: 'draft', label: createDraft.label, on: false, disabled: !createDraft.enabled, onClick: () => cmd.mutate({ action: createDraft }) }] : []),
        ...(publish ? [{ key: 'pub', label: publish.label, on: false, disabled: !publish.enabled, onClick: () => cmd.mutate({ action: publish, payload: threshold ? { receipt_threshold: Number(threshold) } : {} }) }] : []),
      ]}
      meta={d ? [
        { k: 'Policy', v: d.policy_id },
        { k: 'Version', v: `v${d.version}` },
        { k: 'Rules', v: String(d.rules.length) },
        { k: 'Created', v: d.created_at?.slice(0, 10) ?? '—' },
        { k: 'Status', v: d.version === latest ? 'Active' : 'Superseded' },
      ] : []}
      draft={publish ? { threshold, onThreshold: setThreshold, err: cmd.error ? cmd.error.message : null } : null}
      groups={policyGroups(d)}
      pin=""
    />
  );
}
