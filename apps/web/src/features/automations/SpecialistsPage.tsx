'use client';

import { useState } from 'react';
import { SpecialistsView, type SpecialistDetailVM } from '@/components/automations/SpecialistsView';
import { isNotAvailable, useAutomationCommand, useSpecialists } from './api';
import type { SpecialistView } from './contract';

const MODE: Record<string, string> = { replay: 'Replay', live: 'Live' };

function detailOf(sp: SpecialistView): SpecialistDetailVM {
  const add = sp.available_actions.find((a) => a.command === 'add_specialist_to_workflow');
  return {
    id: sp.specialist_id,
    name: sp.name,
    kind: sp.kind_label,
    usedIn: sp.used_in.length ? `Used in ${sp.used_in.join(', ')}` : 'Not in a workflow',
    status: sp.required_control ? 'Required control' : sp.status === 'draft' ? 'Draft' : sp.used_in.length ? 'In use' : 'Published',
    statusDot: sp.required_control ? 'rq' : sp.status === 'draft' ? 'work' : sp.used_in.length ? 'used' : null,
    required: sp.required_control,
    isDraft: sp.status === 'draft',
    rows: [
      { k: 'Purpose', v: sp.purpose },
      { k: 'Permitted records', v: sp.records.join(', ') || '—' },
      { k: 'Tools', v: sp.tools.join(', ') || '—' },
      { k: 'Output', v: sp.output_type },
      { k: 'Handoff', v: sp.handoff },
      { k: 'Execution mode', v: MODE[sp.execution_mode] ?? sp.execution_mode },
      { k: 'Cannot', v: sp.prohibitions.join(', ') || '—' },
    ],
    permLine: `${sp.can_configure.length} configurable · ${sp.prohibitions.length} restricted by Vera`,
    canConfigure: sp.can_configure,
    restricted: sp.prohibitions,
    wfName: 'Card charge investigation',
    canAddToWorkflow: !!add?.enabled,
    addBlockedReason: add?.blocked_reason ?? null,
  };
}

export function SpecialistsPage() {
  const q = useSpecialists();
  const cmd = useAutomationCommand();
  const [sel, setSel] = useState<string | null>(null);
  const list = q.data?.specialists ?? [];
  const cur = list.find((x) => x.specialist_id === sel) ?? list[0] ?? null;
  const notice = q.isPending ? 'Loading specialists…' : q.isError ? (isNotAvailable(q.error) ? 'Not available yet' : (q.error as Error).message) : null;
  const create = q.data?.available_actions.find((a) => a.command === 'create_specialist_draft');
  return (
    <SpecialistsView
      notice={notice}
      ctxTitle="Card charge investigation"
      ctxMeta={`${list.length} specialists`}
      ctxState={notice ?? ''}
      items={list.map((x) => ({ id: x.specialist_id, name: x.name, sub: x.required_control ? 'Required control' : x.status === 'draft' ? 'Draft' : x.kind_label, required: x.required_control, draft: x.status === 'draft' }))}
      selectedId={cur?.specialist_id ?? null}
      onSelect={setSel}
      detail={cur ? detailOf(cur) : null}
      error={cmd.error ? cmd.error.message : null}
      canCreate={!!create?.enabled}
      options={q.data?.options ?? null}
      restricted={q.data?.restricted ?? []}
      onCreate={(input) => create && cmd.mutate({ action: create, payload: { ...input } })}
      onAddToWorkflow={(id) => {
        const a = list.find((x) => x.specialist_id === id)?.available_actions.find((x) => x.command === 'add_specialist_to_workflow');
        if (a) cmd.mutate({ action: a });
      }}
    />
  );
}
