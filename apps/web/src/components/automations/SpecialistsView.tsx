'use client';

import { useState } from 'react';
import { Button } from '@/design-system/primitives/Button';
import s from './automations.module.css';
import { cx } from './WorkflowCanvas';

// Ported from the prototype's `isAgents` block: list, detail, permissions, add-to-workflow, new-specialist drawer.

export type SpecialistItem = {
  id: string;
  name: string;
  sub: string;
  required: boolean;
  draft: boolean;
};
export type SpecialistDetailVM = {
  id: string;
  name: string;
  kind: string;
  usedIn: string;
  status: string;
  statusDot: 'used' | 'work' | 'rq' | null;
  required: boolean;
  isDraft: boolean;
  rows: { k: string; v: string }[];
  permLine: string;
  canConfigure: string[];
  restricted: string[];
  wfName: string;
  canAddToWorkflow: boolean;
  addBlockedReason?: string | null;
};
export type NewSpecialistOptions = { records: string[]; tools: string[]; outputs: string[]; handoffs: string[] } | null;
export type NewSpecialistInput = { name: string; purpose: string; records: string[]; tools: string[]; output_type: string; handoff: string; execution_mode: 'replay' | 'live' };

export type SpecialistsViewProps = {
  notice?: string | null;
  ctxTitle: string;
  ctxMeta: string;
  ctxState: string;
  items: SpecialistItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  detail: SpecialistDetailVM | null;
  error: string | null;
  canCreate: boolean;
  options: NewSpecialistOptions;
  restricted: string[];
  onCreate: (input: NewSpecialistInput) => void;
  onAddToWorkflow: (id: string) => void;
  onViewWorkflow?: () => void;
};

export function SpecialistsView(p: SpecialistsViewProps) {
  const [permOpen, setPermOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [nfOpen, setNfOpen] = useState(false);
  const d = p.detail;
  return (
    <div className={s.wrap}>
      <h2 className={s.h2}>Specialists</h2>
      <div className={s.wfctx} aria-live="polite">
        <div className={s['wfctx-l']}><div className={s['wfctx-t']}>{p.ctxTitle}</div><div className={s['wfctx-m']}>{p.ctxMeta}</div></div>
        <div className={s['wfctx-r']}><span><span className={s['wfctx-s']}>{p.ctxState}</span></span></div>
      </div>
      {p.error ? <p className={s['sp-note']} role="alert">{p.error}</p> : null}
      <div className={s.sp}>
        <div className={s['sp-lw']}>
          <nav className={s['sp-l']} aria-label="Specialists">
            {p.items.map((a) => (
              <button key={a.id} type="button" className={cx(s['sp-i'], a.id === p.selectedId && s.on, a.required && s.pcrow)} onClick={() => p.onSelect(a.id)} aria-current={a.id === p.selectedId ? 'true' : undefined}>
                <span className={s['sp-i-t']}><span className={s['sp-n']}>{a.name}</span><span className={cx(s['sp-st'], a.required && s.sreq, a.draft && s.work)}>{a.sub}</span></span>
              </button>
            ))}
            {p.items.length ? null : <div className={s['sp-i']}><span className={s['sp-st']}>{p.notice ?? 'No specialists.'}</span></div>}
          </nav>
          <button type="button" className={s['sp-new']} onClick={() => setNfOpen(true)} disabled={!p.canCreate}>+ New finance specialist</button>
        </div>
        <section className={cx(s.card, s['sp-d'])} aria-labelledby="sp-name">
          {d ? (
            <>
              <div className={s['sp-h']}>
                <div style={{ minWidth: 0 }}>
                  <h2 className={s['sp-t']} id="sp-name">{d.name}</h2>
                  <div className={s['sp-k']}>{d.kind} · {d.usedIn}</div>
                  <div className={s['sp-s']}><span className={cx(s['sp-dot'], d.statusDot && s[d.statusDot])} aria-hidden="true" />Status: {d.status}</div>
                </div>
                <div className={s['sp-acts']}>
                  {d.isDraft ? <Button variant="sm" onClick={() => setAdding(true)} disabled={!d.canAddToWorkflow} title={d.addBlockedReason ?? undefined}>Add to workflow</Button> : null}
                  {p.onViewWorkflow ? <Button variant={['sm', 'ghost']} onClick={p.onViewWorkflow}>View workflow</Button> : null}
                </div>
              </div>
              {d.required ? <p className={s['sp-pc']}>Required control · Always enforced. Deterministic rules, not a model. It can’t be deleted, disabled, re-instructed or removed from payment or credit workflows.</p> : null}
              {adding ? (
                <div className={s['sp-add']} role="group" aria-label="Add to workflow">
                  <div className={s['sp-add-h']}>Add to workflow</div>
                  <label className={s['sp-add-o']}><input type="radio" defaultChecked name="wfpick" /><span><b>{d.wfName}</b><span className={s.rd}>Approved workflow</span></span></label>
                  <p className={s.rd} style={{ margin: '8px 0 0' }}>Adding this specialist creates a new workflow draft. Existing cases remain on their current version.</p>
                  <div className={s.opts} style={{ marginTop: 10 }}>
                    <Button variant={['sm', 'dark']} onClick={() => { p.onAddToWorkflow(d.id); setAdding(false); }}>Create workflow draft</Button>
                    <Button variant={['sm', 'ghost']} onClick={() => setAdding(false)}>Cancel</Button>
                  </div>
                </div>
              ) : null}
              <dl className={s['sp-tbl']}>{d.rows.map((r) => [<dt key={`k${r.k}`}>{r.k}</dt>, <dd key={`v${r.k}`}>{r.v}</dd>])}</dl>
              <div className={s['sp-row']}>
                <div className={s['sp-rk']}>Permissions</div>
                <div className={s['sp-rv']}><span>{d.permLine}</span><button type="button" className={s.linkb} onClick={() => setPermOpen((o) => !o)} aria-expanded={permOpen}>{permOpen ? 'Hide permissions' : 'View permissions'}</button></div>
              </div>
              {permOpen ? (
                <div className={s['sp-perm']}>
                  <div><h3>Can configure</h3><ul>{d.canConfigure.map((x) => <li key={x}>{x}</li>)}</ul></div>
                  <div><h3>Restricted by Vera</h3><ul>{d.restricted.map((x) => <li key={x}>{x}</li>)}</ul></div>
                </div>
              ) : null}
              <div className={s['sp-row']}>
                <div className={s['sp-rk']}>Appearance</div>
                <div className={s['sp-rv']}><span className={s['sp-av']} /><span>Default</span></div>
              </div>
            </>
          ) : (
            <p className={s.rd}>{p.notice ?? 'Select a specialist.'}</p>
          )}
        </section>
      </div>
      {nfOpen ? <NewSpecialistDrawer options={p.options} restricted={p.restricted} onCancel={() => setNfOpen(false)} onSave={(v) => { p.onCreate(v); setNfOpen(false); }} /> : null}
    </div>
  );
}

function NewSpecialistDrawer({ options, restricted, onCancel, onSave }: { options: NewSpecialistOptions; restricted: string[]; onCancel: () => void; onSave: (v: NewSpecialistInput) => void }) {
  const [v, setV] = useState<NewSpecialistInput>({ name: '', purpose: '', records: [], tools: [], output_type: '', handoff: '', execution_mode: 'replay' });
  const toggle = (k: 'records' | 'tools', x: string) => setV((o) => ({ ...o, [k]: o[k].includes(x) ? o[k].filter((y) => y !== x) : [...o[k], x] }));
  const chips = (list: string[] | undefined, on: (x: string) => boolean, go: (x: string) => void) =>
    list?.length ? list.map((x) => <button key={x} type="button" className={cx(s['nf-c'], on(x) && s.on)} aria-pressed={on(x)} onClick={() => go(x)}>{x}</button>) : <span className={s.rd}>Not available yet</span>;
  return (
    <>
      <button type="button" className={s['nf-scrim']} aria-label="Close" onClick={onCancel} />
      <aside className={s.nf} role="dialog" aria-modal="true" aria-labelledby="nf-t" onKeyDown={(e) => e.key === 'Escape' && onCancel()}>
        <div className={s['nf-h']}><h2 id="nf-t" className={s['nf-t']}>New finance specialist</h2><Button variant={['sm', 'ghost']} aria-label="Close" onClick={onCancel}>✕</Button></div>
        <div className={s['nf-b']}>
          <p className={s['nf-s']}>Create a bounded finance specialist. It can investigate, compare, draft, recommend, or hand off—but cannot move money or override policy.</p>
          <div className={s.field}><label htmlFor="nf-name">Name</label><input id="nf-name" className={s.input} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="e.g. Vendor Match Reviewer" /></div>
          <div className={s.field}><label htmlFor="nf-p">Purpose</label><textarea id="nf-p" className={s.ta} style={{ minHeight: 56 }} value={v.purpose} onChange={(e) => setV({ ...v, purpose: e.target.value })} placeholder="What it checks and why" /></div>
          <div><div className={s['nf-l']}>Permitted records</div><div className={s['nf-cs']}>{chips(options?.records, (x) => v.records.includes(x), (x) => toggle('records', x))}</div></div>
          <div><div className={s['nf-l']}>Permitted tools <span className={s.rd}>· approved library</span></div><div className={s['nf-cs']}>{chips(options?.tools, (x) => v.tools.includes(x), (x) => toggle('tools', x))}</div></div>
          <div><div className={s['nf-l']}>Output record type</div><div className={s['nf-cs']}>{chips(options?.outputs, (x) => v.output_type === x, (x) => setV({ ...v, output_type: x }))}</div></div>
          <div className={s.field}><label htmlFor="nf-h">Handoff target</label><select id="nf-h" className={s.input} value={v.handoff} onChange={(e) => setV({ ...v, handoff: e.target.value })}><option value="">Select…</option>{options?.handoffs.map((h) => <option key={h} value={h}>{h}</option>)}</select></div>
          <div><div className={s['nf-l']}>Execution mode</div><div className={s['nf-cs']}>{(['replay', 'live'] as const).map((m) => <button key={m} type="button" className={cx(s['nf-c'], v.execution_mode === m && s.on)} aria-pressed={v.execution_mode === m} onClick={() => setV({ ...v, execution_mode: m })}>{m === 'replay' ? 'Replay' : 'Live'}</button>)}</div></div>
          <details className={s['nf-d']}><summary>Restricted by Vera</summary><ul className={s['nf-r']}>{restricted.map((x) => <li key={x}>{x}</li>)}</ul></details>
        </div>
        <div className={s['nf-f']}>
          <div className={s.opts} style={{ margin: 0 }}>
            <Button variant="go" onClick={() => onSave(v)}>Save as draft</Button>
            <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          </div>
        </div>
      </aside>
    </>
  );
}
