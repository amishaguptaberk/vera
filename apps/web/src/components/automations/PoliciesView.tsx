'use client';

import { Button } from '@/design-system/primitives/Button';
import s from './automations.module.css';
import { cx } from './WorkflowCanvas';

// Ported from the prototype's `isPolicies` block.

export type PolicyRuleRow = { id: string; rule: string; ev: string; eff: string; ex: string };
export type PoliciesViewProps = {
  title: string;
  sub: string;
  acts: { key: string; label: string; on: boolean; disabled?: boolean; onClick: () => void }[];
  meta: { k: string; v: string }[];
  draft: { threshold: string; onThreshold: (v: string) => void; err: string | null } | null;
  groups: { label: string; rules: PolicyRuleRow[] }[];
  pin: string;
  notice?: string | null;
};

export function PoliciesView(p: PoliciesViewProps) {
  return (
    <div className={s.wrap}>
      <h2 className={s.h2}>Policies</h2>
      <p className={s.sub2}>Deterministic rules enforced by the Policy Controller. Chat, specialist output or agreement between specialists can’t override them.</p>
      <section className={cx(s.card, s.pad)}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div><h2 className={s['sec-t']} style={{ margin: 0, fontSize: 16 }}>{p.title}</h2><div className={s.rd}>{p.sub}</div></div>
          <div className={s.opts} style={{ margin: 0 }}>
            {p.acts.map((a) => <Button key={a.key} variant={a.on ? ['sm', 'dark'] : 'sm'} disabled={a.disabled} onClick={a.onClick}>{a.label}</Button>)}
          </div>
        </div>
        <dl className={s.polmeta}>{p.meta.map((m) => <div key={m.k}><dt className={s.k}>{m.k}</dt><dd className={s.v} style={{ margin: 0 }}>{m.v}</dd></div>)}</dl>
        {p.draft ? (
          <>
            <div className={s.field} style={{ marginTop: 14, maxWidth: 320 }}>
              <label htmlFor="thr">Receipt threshold (USD) · the only editable value in this policy</label>
              <input id="thr" className={s.input} value={p.draft.threshold} onChange={(e) => p.draft!.onThreshold(e.target.value)} />
            </div>
            {p.draft.err ? <div className={s.err} role="alert">{p.draft.err}</div> : null}
          </>
        ) : null}
        {p.notice ? <p className={s.rd}>{p.notice}</p> : null}
        <div className={s.ptw} tabIndex={0} role="region" aria-label="Policy rules">
          {p.groups.map((g) => (
            <div key={g.label}>
              <h3 className={s.polg}>{g.label}</h3>
              <table className={s.pt}>
                <thead><tr><th scope="col" style={{ width: '34%' }}>Requirement</th><th scope="col">Evidence source</th><th scope="col">Effect on case</th><th scope="col">Example record</th></tr></thead>
                <tbody>{g.rules.map((r) => <tr key={r.id}><td>{r.rule}</td><td>{r.ev}</td><td>{r.eff}</td><td className={s.ex}>{r.ex}</td></tr>)}</tbody>
              </table>
            </div>
          ))}
        </div>
        <p className={s.ctlnote}>Required controls are enforced before the case can advance.</p>
        <p className={s.rd} style={{ marginTop: 6 }}>{p.pin}</p>
      </section>
    </div>
  );
}
