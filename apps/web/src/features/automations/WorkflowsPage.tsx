'use client';

import { useState } from 'react';
import { WorkflowBuilderView, type ChecksVM, type InspectorVM, type ToolbarAction, type ValidationRow } from '@/components/automations/WorkflowBuilderView';
import type { CanvasCategory, CanvasEdge, CanvasNode, IconKey, Selection } from '@/components/automations/WorkflowCanvas';
import type { ButtonVariant } from '@/design-system/primitives/Button';
import { isNotAvailable, useAutomationCommand, useWorkflow } from './api';
import { WORKFLOW_ID, type WorkflowDetail, type WorkflowNode, type WorkflowVersion } from './contract';
import { LANES, layoutGraph } from './layout';

const TYPEL: Record<CanvasCategory, string> = {
  trigger: 'Trigger',
  agent: 'Finance specialist',
  policy: 'Policy check · deterministic',
  checkpoint: 'Human checkpoint',
  action: 'Action · simulated in this environment',
};
const SUB: Record<CanvasCategory, string> = { trigger: 'Trigger', agent: 'Automatic', policy: 'Deterministic', checkpoint: 'Human approval', action: 'Simulated action' };
const VARIANT: Record<string, ButtonVariant[]> = {
  run_workflow_checks: ['sm', 'dark'],
  publish_workflow_version: ['sm', 'go'],
  discard_workflow_draft: ['sm', 'ghost'],
};

/** Prototype ICO(): icon by visual type and step. */
function ico(n: WorkflowNode): IconKey {
  if (n.category === 'trigger') return 'in';
  if (n.category === 'policy') return /^retry/.test(n.key) ? 'retry' : 'rules';
  if (n.category === 'action') return /dispute/.test(n.key) ? 'doc' : 'card';
  if (n.category === 'checkpoint') return n.kind === 'close_case' ? 'done' : /handoff/.test(n.key) ? 'handoff' : /admin/.test(n.key) ? 'lock' : 'approve';
  return 'spark';
}

const edgeId = (e: { source: string; target: string; outcome: string }) => `${e.source}>${e.target}:${e.outcome}`;

export function WorkflowsPage({ workflowId = WORKFLOW_ID }: { workflowId?: string }) {
  const q = useWorkflow(workflowId);
  if (q.isPending) return <WorkflowShell message="Loading workflow…" />;
  if (q.isError) return <WorkflowShell message={isNotAvailable(q.error) ? 'Not available yet' : q.error.message} />;
  return <WorkflowBuilder detail={q.data} />;
}

function WorkflowShell({ message }: { message: string }) {
  return (
    <WorkflowBuilderView
      name="Card charge investigation"
      versions={[]}
      status={message}
      actions={[]}
      err={null}
      pub={null}
      pin=""
      nodes={[]}
      edges={[]}
      outline={[]}
      selected={null}
      onSelect={() => {}}
      inspector={null}
      edgeInspector={null}
      validation={[]}
      checks={null}
      versionLog={[]}
    />
  );
}

export function WorkflowBuilder({ detail }: { detail: WorkflowDetail }) {
  const [view, setView] = useState<'draft' | number>(detail.draft ? 'draft' : detail.active_version);
  const [selected, setSelected] = useState<Selection>(null);
  const cmd = useAutomationCommand();

  const current: WorkflowVersion | undefined = view === 'draft' && detail.draft ? detail.draft : detail.versions.find((v) => v.version === view) ?? detail.versions.find((v) => v.version === detail.active_version);
  const graph = current?.graph ?? { nodes: [], edges: [] };
  const isDraft = current?.status === 'draft';
  const pos = layoutGraph(graph);
  const byKey = new Map(graph.nodes.map((n) => [n.key, n]));
  const label = (k: string | null) => (k ? byKey.get(k)?.label ?? k : '—');
  const violations = current?.violations ?? [];
  const badN: Record<string, string> = {};
  violations.forEach((v) => v.node_ids.forEach((k) => (badN[k] = badN[k] ?? v.message)));

  const nodes: CanvasNode[] = graph.nodes.map((n) => ({
    key: n.key,
    name: n.label,
    sub: n.category === 'agent' ? (n.analyst_started ? 'Analyst-started' : 'Automatic') : SUB[n.category],
    category: n.category,
    ico: ico(n),
    x: pos[n.key].x,
    y: pos[n.key].y,
    inPort: n.kind !== 'trigger',
    outPort: n.kind !== 'close_case',
    bad: badN[n.key] ?? null,
  }));
  const edges: CanvasEdge[] = graph.edges.map((e) => ({
    id: edgeId(e),
    from: e.source,
    to: e.target,
    label: e.outcome,
    max: e.max,
    fail: !!byKey.get(e.source)?.failure_outcomes.includes(e.outcome),
    lane: LANES[edgeId(e)] ?? null,
    bad: violations.some((v) => v.node_ids.includes(e.source) && v.node_ids.includes(e.target)),
  }));

  const updateAction = detail.available_actions.find((a) => a.command === 'update_workflow_draft');
  const run = (command: string, payload?: Record<string, unknown>) => {
    const action = detail.available_actions.find((a) => a.command === command);
    if (action) cmd.mutate({ action, payload });
  };

  const selNode = selected?.t === 'node' ? byKey.get(selected.k) : undefined;
  const inspector: InspectorVM | null = selNode
    ? {
        typeLabel: TYPEL[selNode.category],
        name: selNode.label,
        desc: SUB[selNode.category],
        ico: ico(selNode),
        category: selNode.category,
        issue: badN[selNode.key] ?? null,
        rows: [
          { k: 'Step', v: selNode.key },
          { k: 'Kind', v: selNode.kind.replace(/_/g, ' ') },
          { k: 'Started', v: selNode.analyst_started ? 'Analyst-started' : 'Automatic' },
          ...(selNode.provides.length ? [{ k: 'Controls', v: selNode.provides.join(', ').replace(/_/g, ' ') }] : []),
          ...(selNode.money_affecting ? [{ k: 'Money', v: 'Money-affecting · simulated' }] : []),
        ],
        outs: graph.edges.filter((e) => e.source === selNode.key).map((e) => ({ label: e.outcome, to: label(e.target), toKey: e.target })),
        fail: selNode.failure_outcomes.length
          ? selNode.failure_outcomes.map((o) => `${o} → ${graph.edges.filter((e) => e.source === selNode.key && e.outcome === o).map((e) => label(e.target)).join(', ') || 'no path'}`).join(' · ')
          : 'No failure outcome declared.',
        // Required controls (nodes that supply a control), the trigger and close are never removable here.
        canRemove: isDraft && !!updateAction && selNode.provides.length === 0 && selNode.kind !== 'trigger' && selNode.kind !== 'close_case',
        onRemove: () => run('update_workflow_draft', { ops: [{ op: 'remove_node', key: selNode.key }] }),
      }
    : null;
  const selEdge = selected?.t === 'edge' ? graph.edges.find((e) => edgeId(e) === selected.k) : undefined;
  const edgeInspector = selEdge
    ? { name: `${label(selEdge.source)} → ${label(selEdge.target)}`, from: label(selEdge.source), to: label(selEdge.target), fromKey: selEdge.source, toKey: selEdge.target, outcome: selEdge.outcome, max: selEdge.max, issue: null }
    : null;

  const ruleNames = Object.entries(detail.rules ?? {});
  const validation: ValidationRow[] = ruleNames.length
    ? ruleNames.map(([rule, name]) => {
        const v = violations.find((x) => String(x.rule) === rule);
        return { key: rule, text: v ? v.message : name, ok: !v, target: v?.node_ids[0] ?? null };
      })
    : violations.map((v, i) => ({ key: String(i), text: v.message, ok: false, target: v.node_ids[0] ?? null }));

  const checks: ChecksVM = current?.checks
    ? {
        ok: current.checks.passed,
        result: `${current.checks.passed ? 'Passed' : 'Needs attention'} · ${current.checks.results.length} checks`,
        workflow: `Charge investigation v${current.version}`,
        run: current.checks.run_id,
        scenarios: current.checks.results.map((r) => ({
          key: r.scenario,
          label: r.scenario,
          passed: r.passed,
          outcome: r.passed ? 'Passed' : 'Failed',
          last: label(r.last_step),
          steps: r.steps,
          reason: r.reason,
          trace: r.trace.map((t) => ({ n: t.step, node: t.node, action: label(t.node), who: t.kind.replace(/_/g, ' '), result: t.outcome ?? '—' })),
        })),
      }
    : null;

  const actions: ToolbarAction[] = detail.available_actions
    .filter((a) => a.command !== 'update_workflow_draft')
    .map((a) => ({ command: a.command, label: a.label, enabled: a.enabled && !cmd.isPending, blockedReason: a.blocked_reason, variant: VARIANT[a.command] ?? ['sm'], onRun: () => cmd.mutate({ action: a }) }));

  const pin = detail.pinned_cases
    .map((c) => (c.version === detail.active_version ? `Used by ${c.case_id}` : `${c.case_id} stays on v${c.version} · new cases use v${detail.active_version}`))
    .join(' · ');

  return (
    <WorkflowBuilderView
      name={detail.name}
      versions={[
        ...detail.versions
          .filter((v) => v.status === 'published')
          .map((v) => ({
            key: String(v.version),
            label: `v${v.version}${v.version === detail.active_version ? ' · Active' : ''}${detail.pinned_cases.filter((c) => c.version === v.version).map((c) => ` · ${c.case_id}`).join('')}`,
            on: view === v.version,
            draft: false,
            onClick: () => { setView(v.version); setSelected(null); },
          })),
        ...(detail.draft ? [{ key: 'draft', label: `v${detail.draft.version} · Draft`, on: view === 'draft', draft: true, onClick: () => { setView('draft'); setSelected(null); } }] : []),
      ]}
      status={
        isDraft && current
          ? `Draft v${current.version} · not active · based on v${current.based_on ?? detail.active_version}`
          : current?.version === detail.active_version
            ? `v${detail.active_version} · Active · editing creates a draft`
            : `v${current?.version ?? ''} · read-only`
      }
      actions={actions}
      err={cmd.error ? cmd.error.message : null}
      pub={null}
      pin={pin}
      nodes={nodes}
      edges={edges}
      outline={[...graph.nodes]
        .sort((a, b) => pos[a.key].x - pos[b.key].x || pos[a.key].y - pos[b.key].y)
        .map((n) => ({
          key: n.key,
          name: n.label,
          type: TYPEL[n.category],
          outs: graph.edges.filter((e) => e.source === n.key).map((e) => `${e.outcome || 'next'} → ${label(e.target)}`).join(' · ') || '—',
          bad: !!badN[n.key],
        }))}
      selected={selected}
      onSelect={setSelected}
      inspector={inspector}
      edgeInspector={edgeInspector}
      validation={validation}
      checks={checks}
      initialTab={checks ? 'test' : 'validation'}
      versionLog={detail.versions.filter((v) => v.status === 'published').map((v) => ({ t: `v${v.version} published`, at: v.published_at ?? '' }))}
    />
  );
}
