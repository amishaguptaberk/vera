'use client';

import { useState } from 'react';
import { Button, type ButtonVariant } from '@/design-system/primitives/Button';
import s from './automations.module.css';
import { Icon, WorkflowCanvas, cx, type CanvasCategory, type CanvasEdge, type CanvasNode, type IconKey, type Selection } from './WorkflowCanvas';

// Ported from the prototype's `isWorkflows` block (toolbar, banners, canvas/outline, inspector, checks drawer).

export type ToolbarAction = { command: string; label: string; enabled: boolean; blockedReason?: string | null; variant: ButtonVariant[]; onRun: () => void };
export type VersionChip = { key: string; label: string; on: boolean; draft: boolean; onClick: () => void };
export type InspectorVM = {
  typeLabel: string;
  name: string;
  desc: string;
  ico: IconKey;
  category: CanvasCategory;
  issue: string | null;
  rows: { k: string; v: string }[];
  outs: { label: string; to: string; toKey: string }[];
  fail: string;
  /** Required controls and trigger/close are never removable in the UI. */
  canRemove: boolean;
  onRemove?: () => void;
};
export type ValidationRow = { key: string; text: string; ok: boolean; target: string | null };
export type TraceRow = { n: number; node: string; action: string; who: string; result: string };
export type ScenarioRow = { key: string; label: string; passed: boolean; outcome: string; last: string; steps: number; reason: string | null; trace: TraceRow[] };
export type ChecksVM = { result: string; ok: boolean; workflow: string; run: string; scenarios: ScenarioRow[] } | null;
export type OutlineRow = { key: string; name: string; type: string; outs: string; bad: boolean };

export type WorkflowBuilderViewProps = {
  name: string;
  versions: VersionChip[];
  status: string;
  actions: ToolbarAction[];
  err: string | null;
  pub: string | null;
  pin: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  outline: OutlineRow[];
  selected: Selection;
  onSelect: (sel: Selection) => void;
  inspector: InspectorVM | null;
  edgeInspector: { name: string; from: string; to: string; fromKey: string; toKey: string; outcome: string; max: number | null; issue: string | null } | null;
  validation: ValidationRow[];
  checks: ChecksVM;
  versionLog: { t: string; at: string }[];
  /** Which drawer tab opens first (e.g. 'test' after checks ran). */
  initialTab?: Tab;
};

type Tab = 'validation' | 'test' | 'compare' | 'history';
type Height = 'full' | 'compact';

export function WorkflowBuilderView(p: WorkflowBuilderViewProps) {
  const [outlineOn, setOutlineOn] = useState(false);
  const [tab, setTab] = useState<Tab | null>(p.initialTab ?? 'validation');
  const [lastTab, setLastTab] = useState<Tab>(p.initialTab ?? 'validation');
  const [height, setHeight] = useState<Height>('full');
  const [insCol, setInsCol] = useState(false);
  const [scenario, setScenario] = useState(0);

  const issues = p.validation.filter((v) => !v.ok).length;
  const sc = p.checks?.scenarios[scenario] ?? p.checks?.scenarios[0] ?? null;
  const runKeys = new Set(sc?.trace.map((t) => t.node) ?? []);
  const nodes = p.checks && tab === 'test' && sc ? p.nodes.map((n) => ({ ...n, run: runKeys.has(n.key) ? (sc.passed || n.key !== sc.trace[sc.trace.length - 1]?.node ? ('ok' as const) : ('fail' as const)) : null })) : p.nodes;
  const edges = p.checks && tab === 'test' && sc ? p.edges.map((e) => ({ ...e, run: runKeys.has(e.from) && runKeys.has(e.to) })) : p.edges;
  const ver = p.versions.find((v) => v.on)?.label.split(' ')[0] ?? '';
  const dSummary = `Workflow checks · ${ver} · ${issues ? `${issues} ${issues === 1 ? 'issue' : 'issues'}` : 'Passed'} · ${p.validation.length} checks`;
  const tabs: { k: Tab; l: string }[] = [
    { k: 'validation', l: 'Validation' + (issues ? ` · ${issues} ${issues === 1 ? 'issue' : 'issues'}` : ' · passing') },
    { k: 'test', l: 'Workflow checks' + (p.checks ? ` · ${p.checks.workflow}` : '') },
    { k: 'compare', l: 'Compare' },
    { k: 'history', l: 'Versions' },
  ];
  const ins = p.inspector;

  return (
    <div className={s.wfb}>
      <h2 className={s.sr}>Workflows</h2>
      <div className={s.wtb}>
        <div className={s['wtb-l']}>
          <div className={s.wname}>{p.name}</div>
          <div className={s.vchs}>
            {p.versions.map((v) => (
              <button key={v.key} type="button" className={cx(s.vch, v.on && s.on, v.draft && s.draft)} onClick={v.onClick}>{v.label}</button>
            ))}
          </div>
        </div>
        <div className={s['wtb-s']}>{p.status}</div>
        <div className={s['wtb-r']}>
          <Button variant={['sm', 'ghost']} onClick={() => setOutlineOn((o) => !o)}>{outlineOn ? 'Canvas' : 'Outline'}</Button>
          {p.actions.map((a) => (
            <Button key={a.command} variant={a.variant} disabled={!a.enabled} title={a.blockedReason ?? undefined} onClick={a.onRun}>{a.label}</Button>
          ))}
        </div>
      </div>
      {p.err ? <div className={cx(s.wbar, s.bad)} role="alert">{p.err}</div> : null}
      {p.pub ? <div className={s.wbar}>{p.pub}</div> : null}
      <div className={s.wbody}>
        {outlineOn ? (
          <div className={s.outl}>
            <p className={s.rd} style={{ margin: '0 0 8px' }}>Outline of the same graph. Select a step to open it on the canvas.</p>
            <table className={s.pt}>
              <thead><tr><th>Step</th><th>Type</th><th>Outcomes → next step</th></tr></thead>
              <tbody>
                {p.outline.map((o) => (
                  <tr key={o.key} className={o.bad ? s.bad : undefined}>
                    <td><button type="button" className={s.linkb} onClick={() => { setOutlineOn(false); p.onSelect({ t: 'node', k: o.key }); }}>{o.name}</button></td>
                    <td>{o.type}</td>
                    <td>{o.outs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {/* The canvas stays mounted while the outline is shown so zoom and pan persist. */}
        <div style={outlineOn ? { display: 'none' } : { display: 'contents' }}>
          <WorkflowCanvas nodes={nodes} edges={edges} selected={p.selected} onSelect={p.onSelect} hasRun={!!(p.checks && tab === 'test')} />
        </div>
        {ins || p.edgeInspector ? (
          <aside className={cx(s.ins, insCol && s.col)} style={insCol ? undefined : { width: 340 }} aria-label="Inspector">
            <div className={s['ins-h']}>
              <span className={s.lbl}>{ins ? ins.typeLabel : 'Path'}</span>
              <span style={{ display: 'flex', gap: 2 }}>
                <Button variant={['sm', 'ghost']} onClick={() => setInsCol((c) => !c)} aria-label={insCol ? 'Expand inspector' : 'Collapse inspector'} title={insCol ? 'Expand inspector' : 'Collapse inspector'}>{insCol ? '‹' : '›'}</Button>
                <Button variant={['sm', 'ghost']} onClick={() => p.onSelect(null)} aria-label="Close inspector">Close</Button>
              </span>
            </div>
            {ins ? (
              <>
                <div className={s['ins-t']}>
                  <Icon k={ins.ico} className={cx(s.gi, s[`t-${ins.category}`])} />
                  <div><div className={s.it} style={{ fontSize: 16 }} data-testid="inspector-name">{ins.name}</div><div className={s.rd}>{ins.desc}</div></div>
                </div>
                {ins.issue ? <div className={s['ins-bad']}>{ins.issue}</div> : null}
                <div className={cx(s.kv, s['ins-kv'])}>{ins.rows.map((r) => [<div key={`k${r.k}`} className={s.k}>{r.k}</div>, <div key={`v${r.k}`}>{r.v}</div>])}</div>
                <div className={cx(s.rl, s['ins-l'])}>Outcomes</div>
                {ins.outs.map((o) => (
                  <button key={o.label + o.toKey} type="button" className={s['ins-o']} onClick={() => p.onSelect({ t: 'node', k: o.toKey })}><span className={s['ins-ol']}>{o.label}</span><span>→ {o.to}</span></button>
                ))}
                {ins.outs.length ? null : <div className={s.rd}>None. Drag from the step’s right port to another step.</div>}
                <div className={cx(s.rl, s['ins-l'])}>Failure handling</div>
                <div className={s.rd} style={{ color: '#3b3a39' }}>{ins.fail}</div>
                {ins.canRemove && ins.onRemove ? <div className={s['ins-f']}><Button variant={['sm', 'ghost']} onClick={ins.onRemove}>Remove step</Button></div> : null}
              </>
            ) : null}
            {p.edgeInspector ? (
              <>
                <div className={s.it} style={{ fontSize: 16 }}>{p.edgeInspector.name}</div>
                {p.edgeInspector.issue ? <div className={s['ins-bad']}>{p.edgeInspector.issue}</div> : null}
                <div className={cx(s.kv, s['ins-kv'])}>
                  <div className={s.k}>From</div><div><button type="button" className={s.linkb} onClick={() => p.onSelect({ t: 'node', k: p.edgeInspector!.fromKey })}>{p.edgeInspector.from}</button></div>
                  <div className={s.k}>To</div><div><button type="button" className={s.linkb} onClick={() => p.onSelect({ t: 'node', k: p.edgeInspector!.toKey })}>{p.edgeInspector.to}</button></div>
                </div>
                <div className={cx(s.rl, s['ins-l'])}>Runs when the outcome is</div>
                <div className={s.opts}><Button variant={['sm', 'dark']} disabled>{p.edgeInspector.outcome}</Button></div>
                {p.edgeInspector.max ? <><div className={cx(s.rl, s['ins-l'])}>Loop limit</div><div className={s.opts}><Button variant={['sm', 'dark']} disabled>{`max ${p.edgeInspector.max}`}</Button></div><div className={s.rd} style={{ marginTop: 6 }}>A loop without a limit can’t be published.</div></> : null}
              </>
            ) : null}
          </aside>
        ) : null}
      </div>
      <div className={cx(s.drawer, !tab && s.col)}>
        <div className={s.dtabs} role="tablist">
          {tabs.map((t) => (
            <button key={t.k} type="button" role="tab" aria-selected={tab === t.k} className={cx(s.dtab, tab === t.k && s.on)} onClick={() => { const next = tab === t.k ? null : t.k; if (next) setLastTab(next); setTab(next); }}>{t.l}</button>
          ))}
          {!tab ? <button type="button" className={s.dsum} onClick={() => setTab(lastTab)} title="Restore checks panel"><span className={cx(s.slot, issues ? s['s-block'] : s['s-done'])} aria-hidden="true" />{dSummary}</button> : null}
          <span className={s.dpin}>{p.pin}</span>
          <span className={s.dctl}>
            {tab ? (
              <>
                <button type="button" className={s.linkb} onClick={() => setHeight((h) => (h === 'compact' ? 'full' : 'compact'))}>{height === 'compact' ? 'Expand' : 'Compact'}</button>
                <button type="button" className={s.linkb} onClick={() => { setLastTab(tab); setTab(null); }}>Collapse</button>
              </>
            ) : <button type="button" className={s.linkb} onClick={() => setTab(lastTab)}>Expand</button>}
          </span>
        </div>
        {tab ? (
          <div className={s.dbody} style={{ height: height === 'compact' ? 180 : 300 }}>
            {tab === 'validation' ? (
              <div className={s.vgrid}>
                {p.validation.map((c) => (
                  <div key={c.key} className={cx(s.vrow, !c.ok && s.bad)}>
                    <span className={s.m}>{c.ok ? '✓' : '✕'}</span>
                    <span style={{ flex: 1 }}>{c.text}</span>
                    {!c.ok && c.target ? <button type="button" className={s.linkb} onClick={() => p.onSelect({ t: 'node', k: c.target! })}>Show</button> : null}
                  </div>
                ))}
              </div>
            ) : null}
            {tab === 'test' ? (
              !p.checks ? (
                <p className={s.rd} style={{ margin: 0 }}>Workflow checks run every scenario and guard against this version as a dry run. No production records or external services are touched.</p>
              ) : height === 'compact' ? (
                <div className={s['wck-c']}>
                  {p.checks.scenarios.map((t) => (
                    <div key={t.key} className={s['wck-cr']}><span className={t.passed ? s['oc-ok'] : s['oc-bad']}>{t.outcome}</span><span className={s['wck-cn']}>{t.label}</span><span className={s.num}>{t.steps} steps</span><span className={s.num}>—</span></div>
                  ))}
                  <button type="button" className={s.linkb} onClick={() => setHeight('full')}>Open details</button>
                </div>
              ) : (
                <>
                  <div className={s['wck-h']}><span className={s['wck-t']}>Workflow checks</span><span className={cx(s['wck-r'], p.checks.ok ? s.ok : s.bad)}>{p.checks.result}</span></div>
                  <div className={s.wmeta}>
                    <div><span>Scenario </span><b>{sc?.label}</b></div>
                    <div><span>Workflow </span><b>{p.checks.workflow}</b></div>
                    <div><span>Run </span><b>{p.checks.run}</b></div>
                    <div><span>Result </span><b>{sc ? (sc.passed ? 'Reached close' : sc.reason) : '—'}</b></div>
                  </div>
                  <p className={s.rd} style={{ margin: '0 0 10px' }}>Dry run · no production records or external services were touched.</p>
                  <div className={s.wgrid}>
                    <div className={s.wscroll}>
                      <table className={s.wsc}>
                        <thead><tr><th scope="col">Scenario</th><th scope="col">Outcome</th><th scope="col">Last step</th><th scope="col">Steps</th><th scope="col">Run time</th></tr></thead>
                        <tbody>
                          {p.checks.scenarios.map((t, i) => (
                            <tr key={t.key} className={i === scenario ? s.on : undefined}>
                              <td><button type="button" className={s.sb} onClick={() => setScenario(i)}>{t.label}</button>{t.reason ? <div className={s.sec}>{t.reason}</div> : null}</td>
                              <td className={t.passed ? s['oc-ok'] : s['oc-bad']}>{t.outcome}</td>
                              <td>{t.last}</td>
                              <td className={s.num}>{t.steps}</td>
                              <td className={s.num}>—</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className={s['wsplit-v']} aria-hidden="true" />
                    <div className={s.wscroll}>
                      <div className={s.rl} style={{ marginBottom: 4 }}>{sc ? `Trace · ${sc.label}` : ''}</div>
                      <table className={s.wsc}>
                        <thead><tr><th scope="col">Step</th><th scope="col">Action</th><th scope="col">Result</th><th scope="col">Records</th><th scope="col">Policy effect</th></tr></thead>
                        <tbody>
                          {sc?.trace.map((x) => (
                            <tr key={x.n} data-testid="trace-row">
                              <td className={s.num}>{x.n}</td>
                              <td><button type="button" className={s.sb} onClick={() => p.onSelect({ t: 'node', k: x.node })}>{x.action}</button><div className={s.sec}>{x.who}</div></td>
                              <td>{x.result}</td>
                              <td className={s.num}>—</td>
                              <td>—</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <div className={s.rl} style={{ marginTop: 6 }}>{sc ? (sc.passed ? 'Reached close or monitoring.' : `${sc.reason ?? ''}.`) : ''}</div>
                    </div>
                  </div>
                </>
              )
            ) : null}
            {tab === 'compare' ? <p className={s.rd} style={{ margin: 0 }}>Make a change to start a draft. The comparison shows changed steps, paths, settings and how each test scenario’s path differs from the active version.</p> : null}
            {tab === 'history' ? (
              p.versionLog.length ? p.versionLog.map((l) => <div key={l.t + l.at} className={s.evrow}><span>{l.t}</span><span className={s.rd}>{l.at}</span></div>) : <p className={s.rd} style={{ margin: 0 }}>No versions published yet.</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
