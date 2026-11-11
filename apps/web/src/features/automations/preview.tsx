'use client';

// DEVELOPMENT FIXTURES ONLY. The only importer of ./dev-fixtures. Renders the real Automations components with
// contract-conforming fixture data (graph, check results and policy rules dumped from the automations domain
// module; specialists from the prototype's AGENTS data). Command buttons are no-ops. Never imported by pages.
import type { ReactNode } from 'react';
import { PoliciesView } from '@/components/automations/PoliciesView';
import { SpecialistsView } from '@/components/automations/SpecialistsView';
import type { Graph, PolicyDetail, ScenarioResult, SpecialistsView as SpecialistsData, Violation, WorkflowDetail } from './contract';
import policyJson from './dev-fixtures/policy-v1.json';
import specialistsJson from './dev-fixtures/specialists.json';
import wfJson from './dev-fixtures/workflow-v3.json';
import { policyGroups } from './PoliciesPage';
import { WorkflowBuilder } from './WorkflowsPage';

const noop = () => {};
const act = (command: string, label: string, enabled = true, blocked_reason: string | null = null) => ({ command, label, enabled, blocked_reason, idempotency_key: 'preview', payload_defaults: {} });
const wf = wfJson as unknown as {
  graph: Graph;
  results: ScenarioResult[];
  violations: Violation[];
  draftGraph: Graph;
  draftViolations: Violation[];
  draftResults: ScenarioResult[];
  rules: Record<string, string>;
};

const v3 = { version: 3, status: 'published' as const, revision: 0, based_on: 2, graph: wf.graph, violations: wf.violations, checks: null, published_at: 'Nov 3, 2026' };
const base = (over: Partial<WorkflowDetail>): WorkflowDetail => ({
  workflow_id: 'card-dispute',
  name: 'Card charge investigation',
  active_version: 3,
  versions: [v3],
  draft: null,
  pinned_cases: [{ case_id: 'CHG-1042', version: 3 }],
  rules: wf.rules,
  available_actions: [act('create_workflow_draft', 'Edit workflow'), act('run_workflow_checks', 'Run workflow checks')],
  ...over,
});
const badDraft = { version: 4, status: 'draft' as const, revision: 2, based_on: 3, graph: wf.draftGraph, violations: wf.draftViolations, checks: { run_id: 'CHK-4-1', graph_hash: 'preview', passed: wf.draftResults.every((r) => r.passed), results: wf.draftResults }, published_at: null };
const goodDraft = { ...v3, version: 4, status: 'draft' as const, revision: 1, based_on: 3, checks: { run_id: 'CHK-4-2', graph_hash: 'preview', passed: true, results: wf.results }, published_at: null };
const draftActions = (pubOk: boolean) => [
  act('update_workflow_draft', 'Update draft'),
  act('discard_workflow_draft', 'Discard draft'),
  act('run_workflow_checks', 'Run workflow checks'),
  act('publish_workflow_version', 'Publish v4', pubOk, pubOk ? null : 'Validation issues and workflow checks must pass before publishing.'),
];

const sp = specialistsJson as unknown as SpecialistsData;
const pol = policyJson as unknown as PolicyDetail;

export const previewStates: { name: string; render: () => ReactNode }[] = [
  { name: 'Workflow v3 · published (active)', render: () => <WorkflowBuilder onCommand={noop} detail={base({})} /> },
  { name: 'Workflow draft v4 · validation violations · publish blocked', render: () => <WorkflowBuilder onCommand={noop} detail={base({ draft: badDraft, available_actions: draftActions(false) })} /> },
  { name: 'Workflow draft v4 · six checks passed · publish allowed', render: () => <WorkflowBuilder onCommand={noop} detail={base({ draft: goodDraft, available_actions: draftActions(true) })} /> },
  {
    name: 'Specialists · list and detail',
    render: () => (
      <SpecialistsView
        ctxTitle="Card charge investigation"
        ctxMeta={`v3 · ${sp.specialists.length} specialists`}
        ctxState="Active"
        items={sp.specialists.map((x) => ({ id: x.specialist_id, name: x.name, sub: x.required_control ? 'Required control' : x.status === 'draft' ? 'Draft' : x.kind_label, required: x.required_control, draft: x.status === 'draft' }))}
        selectedId={sp.specialists[0].specialist_id}
        onSelect={noop}
        detail={{
          id: sp.specialists[0].specialist_id,
          name: sp.specialists[0].name,
          kind: sp.specialists[0].kind_label,
          usedIn: `Used in ${sp.specialists[0].used_in.join(', ')}`,
          status: 'In use',
          statusDot: 'used',
          required: false,
          isDraft: false,
          rows: [
            { k: 'Purpose', v: sp.specialists[0].purpose },
            { k: 'Permitted records', v: sp.specialists[0].records.join(', ') },
            { k: 'Tools', v: sp.specialists[0].tools.join(', ') },
            { k: 'Output', v: sp.specialists[0].output_type },
            { k: 'Handoff', v: sp.specialists[0].handoff },
            { k: 'Cannot', v: sp.specialists[0].prohibitions.join(', ') },
          ],
          permLine: `${sp.specialists[0].can_configure.length} configurable · ${sp.specialists[0].prohibitions.length} restricted by Vera`,
          canConfigure: sp.specialists[0].can_configure,
          restricted: sp.specialists[0].prohibitions,
          wfName: 'Card charge investigation',
          canAddToWorkflow: false,
        }}
        error={null}
        canCreate
        options={sp.options ?? null}
        restricted={sp.restricted ?? []}
        onCreate={noop}
        onAddToWorkflow={noop}
      />
    ),
  },
  {
    name: 'Policies · v1 published (read-only)',
    render: () => (
      <PoliciesView
        title="Card charge investigation policy"
        sub="v1 · Active"
        acts={[{ key: 'v1', label: 'v1', on: true, onClick: noop }, { key: 'draft', label: 'Create draft', on: false, onClick: noop }]}
        meta={[{ k: 'Policy', v: pol.policy_id }, { k: 'Version', v: 'v1' }, { k: 'Rules', v: String(pol.rules.length) }, { k: 'Created', v: '2026-11-03' }, { k: 'Status', v: 'Active' }]}
        draft={null}
        groups={policyGroups(pol)}
        pin="Used by CHG-1042"
      />
    ),
  },
  {
    name: 'Policies · draft v2 (threshold editable)',
    render: () => (
      <PoliciesView
        title="Card charge investigation policy"
        sub="Draft v2 · based on v1"
        acts={[{ key: 'v1', label: 'v1', on: false, onClick: noop }, { key: 'pub', label: 'Publish v2', on: true, onClick: noop }]}
        meta={[{ k: 'Policy', v: pol.policy_id }, { k: 'Version', v: 'Draft v2' }, { k: 'Rules', v: String(pol.rules.length) }, { k: 'Created', v: '2026-11-11' }, { k: 'Status', v: 'Draft' }]}
        draft={{ threshold: '75', onThreshold: noop, err: null }}
        groups={policyGroups(pol)}
        pin="CHG-1042 stays on v1 · new cases use v2 after publish"
      />
    ),
  },
];
