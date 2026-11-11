'use client';

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { activityQuery, runsQuery, useRunCommand, type ActivityEvent, type CaseView, type RunOut } from '@/api';
import { VeraRail, type RailMessage } from '@/components/decision';
import { actorLabel } from '@/lib';
import { useAsk } from './queries';
import { addPair, type RailPair } from './rail-state';

/** Suggested questions: prototype copy (Main.dc.html `chips`). They are sent verbatim to the server like typed text. */
export const SUGGESTED: Readonly<Record<'analyst' | 'reviewer', readonly string[]>> = {
  analyst: ['What’s missing?', 'Why is credit blocked?', 'Related charges?'],
  reviewer: ['What supports this?', 'What is still unresolved?', 'What would make this stale?'],
};

export type VeraRailPanelProps = {
  c: CaseView;
  role: 'analyst' | 'reviewer';
  open: boolean;
  onClose: () => void;
  selected?: string | null;
  onSelectRecord: (recordId: string) => void;
  /** Navigation actions returned by the server (e.g. "Open decision"). */
  onNavigate?: (target: string) => void;
};

const time = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const RUNNING = new Set(['queued', 'running', 'pending']);

/** Work entries from GET /runs (one per run, a line per step) and activity events, oldest first. */
export function workMessages(runs: readonly RunOut[], events: readonly ActivityEvent[]): RailMessage[] {
  const items: { at: string; m: RailMessage }[] = [
    ...runs.map((r) => ({
      at: r.created_at,
      m: {
        kind: 'work' as const,
        id: `run-${r.id}`,
        who: 'Vera · specialists',
        at: time(r.created_at),
        head: `Run ${r.id} · ${r.status}`,
        running: RUNNING.has(r.status),
        lines: r.steps.map((s) => ({ text: `${actorLabel(s.specialist)} · ${s.status}${s.failure_reason ? ` · ${s.failure_reason}` : ''}` })),
      },
    })),
    ...events.map((e) => ({
      at: e.at,
      m: {
        kind: 'vera' as const,
        id: `ev-${e.id}`,
        who: actorLabel(e.actor_name),
        at: time(e.at),
        title: e.summary,
        paras: [],
        cites: e.record_ids.map((id) => ({ record_id: id, label: id })),
      },
    })),
  ];
  return items.sort((a, b) => a.at.localeCompare(b.at)).map((x) => x.m);
}

export function pairMessages(pairs: readonly RailPair[]): RailMessage[] {
  return pairs.flatMap((p): RailMessage[] => [
    { kind: 'user', id: `q-${p.id}`, text: p.question },
    {
      kind: 'vera',
      id: `a-${p.id}`,
      who: 'Vera',
      title: p.response.title ?? null,
      paras: p.response.paragraphs?.length ? p.response.paragraphs : [p.response.answer],
      cites: p.response.citations.map((x) => ({ record_id: x.record_id, label: `${x.record_id} v${x.version}` })),
      actions: (p.response.actions ?? []).map((a, i) => ({ key: `${p.id}:${i}`, label: a.label })),
    },
  ]);
}

/** The Vera rail wired to /runs, /activity and POST /ask. Actions come only from the server response. */
export function VeraRailPanel({ c, role, open, onClose, selected, onSelectRecord, onNavigate }: VeraRailPanelProps) {
  const runs = useQuery(runsQuery(c.case_id));
  const activity = useQuery(activityQuery(c.case_id));
  const ask = useAsk(c.case_id);
  const run = useRunCommand(c.case_id);
  const [pairs, setPairs] = useState<RailPair[]>([]);
  const [input, setInput] = useState('');
  const [err, setErr] = useState<string | null>(null);

  const messages = useMemo(() => {
    const base = workMessages(runs.data ?? [], activity.data?.events ?? []);
    const extra: RailMessage[] = err ? [{ kind: 'sys', id: 'ask-err', text: err }] : [];
    return [...base, ...pairMessages(pairs), ...extra];
  }, [runs.data, activity.data, pairs, err]);

  const onAsk = (text: string) => {
    const q = text.trim();
    if (!q || ask.isPending) return;
    setErr(null);
    ask.mutate(
      { text: q },
      {
        onSuccess: (r) => {
          setInput('');
          setPairs((prev) => addPair(prev, q, r));
        },
        onError: (e) => setErr(e.status === 404 ? 'Asking Vera is not available yet.' : e.message),
      },
    );
  };

  const onAction = (key: string) => {
    const [pid, idx] = key.split(':');
    const a = pairs.find((p) => String(p.id) === pid)?.response.actions?.[Number(idx)];
    if (!a) return;
    if (a.nav) return onNavigate?.(a.nav);
    // Only a command the server currently offers on the case can run; the rail never invents one.
    const offered = a.command ? c.available_actions.find((x) => x.command === a.command && x.enabled) : undefined;
    if (offered) run.mutate({ action: offered, caseVersion: c.case_version });
  };

  return (
    <VeraRail
      open={open}
      sub={role === 'reviewer' ? 'Approval context' : null}
      messages={messages}
      emptyText="Vera’s work on this case appears here."
      chips={SUGGESTED[role]}
      input={input}
      placeholder={role === 'reviewer' ? 'Ask about this packet' : 'Ask about this case'}
      sending={ask.isPending}
      selected={selected}
      onInput={setInput}
      onAsk={onAsk}
      onClose={onClose}
      onSelectRecord={onSelectRecord}
      onAction={onAction}
    />
  );
}
