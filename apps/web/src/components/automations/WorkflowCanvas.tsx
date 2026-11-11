'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import s from './automations.module.css';

// Ported from the prototype's workflow canvas (Main.dc.html: G3, gEdgeGeo, cvBind, cvZoom, cvFit, minimap).
// Presentational: positions arrive as props; pan/zoom is local view state and survives re-renders, resizes and
// selection changes (the canvas element is never keyed or re-mounted).

export const NW = 72;
export const NH = 72;

export type CanvasCategory = 'trigger' | 'agent' | 'policy' | 'checkpoint' | 'action';
export type CanvasNode = {
  key: string;
  name: string;
  sub: string;
  category: CanvasCategory;
  ico: IconKey;
  x: number;
  y: number;
  inPort: boolean;
  outPort: boolean;
  /** Server validation message for this node (shown as the `!` badge). */
  bad?: string | null;
  tag?: string | null;
  retry?: string | null;
  /** Dry-run state from a server check result. */
  run?: 'ok' | 'fail' | null;
};
export type CanvasEdge = { id: string; from: string; to: string; label: string; max: number | null; fail: boolean; lane?: number | null; bad?: boolean; run?: boolean };
export type Selection = { t: 'node' | 'edge'; k: string } | null;

export type IconKey = 'in' | 'rules' | 'retry' | 'approve' | 'done' | 'handoff' | 'lock' | 'card' | 'doc' | 'spark';
const ICOP: Record<IconKey, string> = {
  in: 'M12 4v9M8 9.5l4 4 4-4M5 15.5V19h14v-3.5',
  rules: 'M12 3.5 4 7.5l8 4 8-4-8-4zM4 12l8 4 8-4M4 16.5l8 4 8-4',
  retry: 'M5 12a7 7 0 0 1 12.2-4.7M19 12a7 7 0 0 1-12.2 4.7M17.5 3.8v3.7h-3.7M6.5 20.2v-3.7h3.7',
  approve: 'M9.5 7.5a3 3 0 1 0 0 .01M4 19c.7-3 2.9-4.6 5.5-4.6 1.5 0 2.8.5 3.8 1.4M14.5 16.5l2 2 4-4.2',
  done: 'M12 3.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 0 0 0-16.4zM8.3 12.2l2.6 2.6 5-5.4',
  handoff: 'M4 8h11M12 5l3 3-3 3M20 16H9M12 13l-3 3 3 3',
  lock: 'M6.5 10.5h11v9h-11zM8.8 10.5V8a3.2 3.2 0 0 1 6.4 0v2.5M12 14v2',
  card: 'M3.8 6.5h16.4v11H3.8zM3.8 10h16.4M7 14.5h3.5',
  doc: 'M6.5 3.8h7.5l3.5 3.5v12.9h-11zM13.8 3.8v3.7h3.7M9 12h6M9 15.5h4',
  spark: 'M12 4l1.6 4.8L18.5 10l-4.9 1.4L12 16l-1.6-4.6L5.5 10l4.9-1.2z',
};

export function Icon({ k, className }: { k: IconKey; className?: string }) {
  return (
    <span className={className} data-ico={k}>
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={ICOP[k] ?? ICOP.spark} />
      </svg>
    </span>
  );
}

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');

/** Edge geometry, ported verbatim from the prototype's gEdgeGeo. */
export function edgeGeo(a: { x: number; y: number }, b: { x: number; y: number }, lane?: number | null) {
  const sx = a.x + NW, sy = a.y + NH / 2, tx = b.x, ty = b.y + NH / 2;
  if (lane != null || tx < sx + 30) {
    const L = lane != null ? lane : Math.max(a.y, b.y) + NH + 46;
    const x1 = sx + 22, x2 = tx - 22, r = 10;
    const sgn = (v: number) => (v >= 0 ? 1 : -1);
    const d1 = sgn(L - sy), d2 = sgn(ty - L), h = sgn(x2 - x1);
    const d = `M${sx} ${sy} H${x1 - r} Q${x1} ${sy} ${x1} ${sy + d1 * r} V${L - d1 * r} Q${x1} ${L} ${x1 + h * r} ${L} H${x2 - h * r} Q${x2} ${L} ${x2} ${L + d2 * r} V${ty - d2 * r} Q${x2} ${ty} ${x2 + r} ${ty} H${tx}`;
    return { d, lx: (x1 + x2) / 2, ly: L, tx, ty };
  }
  const dx = Math.max(36, (tx - sx) / 2);
  const d = `M${sx} ${sy} C${sx + dx} ${sy} ${tx - dx} ${ty} ${tx} ${ty}`;
  return { d, lx: (sx + tx) / 2, ly: Math.abs(ty - sy) < 4 ? sy - 12 : (sy + ty) / 2, tx, ty };
}

type View = { z: number; px: number; py: number; w: number; h: number; init: boolean };

export type WorkflowCanvasProps = {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  selected: Selection;
  onSelect: (sel: Selection) => void;
  /** True while showing a dry-run trace: untaken steps dim. */
  hasRun?: boolean;
  children?: React.ReactNode;
};

export function WorkflowCanvas({ nodes, edges, selected, onSelect, hasRun = false, children }: WorkflowCanvasProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [cv, setCv] = useState<View>({ z: 0.78, px: 24, py: 40, w: 1200, h: 560, init: false });
  const pan = useRef<{ sx: number; sy: number; px: number; py: number; moved: boolean } | null>(null);

  // Size tracking without re-mounting: a ResizeObserver only updates the viewport size.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setCv((c) => (c.init ? { ...c, w: r.width || c.w, h: r.height || c.h } : { ...c, w: r.width || 1200, h: r.height || 560, py: Math.max(40, Math.round(((r.height || 560) - 820 * 0.78) / 2)), init: true }));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const zoom = useCallback((f: number, px?: number, py?: number) => {
    setCv((c) => {
      const ox = px ?? c.w / 2, oy = py ?? c.h / 2;
      const z2 = Math.min(1.6, Math.max(0.3, c.z * f));
      return { ...c, px: ox - (ox - c.px) * (z2 / c.z), py: oy - (oy - c.py) * (z2 / c.z), z: z2 };
    });
  }, []);

  const fit = useCallback(() => {
    setCv((c) => {
      let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
      nodes.forEach((n) => { minX = Math.min(minX, n.x); minY = Math.min(minY, n.y); maxX = Math.max(maxX, n.x + NW); maxY = Math.max(maxY, n.y + NH); });
      minY = Math.min(minY, 20); maxY = Math.max(maxY, 820);
      const z = Math.min(1.2, Math.max(0.3, Math.min((c.w - 60) / (maxX - minX), (c.h - 40) / (maxY - minY))));
      return { ...c, z, px: (c.w - (maxX - minX) * z) / 2 - minX * z, py: (c.h - (maxY - minY) * z) / 2 - minY * z };
    });
  }, [nodes]);

  // Wheel: scroll pans, Ctrl/⌘+scroll zooms (non-passive so the page does not scroll).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const r = el.getBoundingClientRect();
      if (ev.ctrlKey || ev.metaKey) zoom(ev.deltaY < 0 ? 1.1 : 1 / 1.1, ev.clientX - r.left, ev.clientY - r.top);
      else setCv((c) => ({ ...c, px: c.px - ev.deltaX, py: c.py - ev.deltaY }));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoom]);

  const byKey = new Map(nodes.map((n) => [n.key, n]));
  const geo = edges.flatMap((e) => {
    const a = byKey.get(e.from), b = byKey.get(e.to);
    if (!a || !b) return [];
    return [{ e, g: edgeGeo(a, b, e.lane), loop: b.x <= a.x }];
  });
  const sel = (t: 'node' | 'edge', k: string) => selected?.t === t && selected.k === k;

  // Minimap (prototype geometry).
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  nodes.forEach((n) => { minX = Math.min(minX, n.x); minY = Math.min(minY, n.y); maxX = Math.max(maxX, n.x + NW); maxY = Math.max(maxY, n.y + NH); });
  minX -= 40; minY = Math.min(minY, 20) - 20; maxX += 40; maxY = Math.max(maxY, 760) + 20;
  const MW = 188, MH = 76;
  const ms = Math.min(MW / (maxX - minX), MH / (maxY - minY));

  const worldStyle: CSSProperties = { transform: `translate(${cv.px.toFixed(1)}px, ${cv.py.toFixed(1)}px) scale(${cv.z.toFixed(3)})` };
  const gridStyle: CSSProperties = { backgroundPosition: `${cv.px.toFixed(1)}px ${cv.py.toFixed(1)}px`, backgroundSize: `${(20 * cv.z).toFixed(2)}px ${(20 * cv.z).toFixed(2)}px` };

  return (
    <div
      ref={ref}
      className={s.cvs}
      tabIndex={0}
      aria-label="Workflow canvas. Drag steps to move, drag from a step's right port to connect, scroll to pan, Ctrl+scroll to zoom."
      style={gridStyle}
      data-testid="workflow-canvas"
      onPointerDown={(ev) => {
        const t = ev.target as HTMLElement;
        if (ev.button !== 0 || t.closest('[data-ui],[data-mm],[data-node],[data-edge]')) return;
        pan.current = { sx: ev.clientX, sy: ev.clientY, px: cv.px, py: cv.py, moved: false };
      }}
      onPointerMove={(ev) => {
        const p = pan.current;
        if (!p) return;
        if (Math.abs(ev.clientX - p.sx) + Math.abs(ev.clientY - p.sy) > 3) p.moved = true;
        setCv((c) => ({ ...c, px: p.px + ev.clientX - p.sx, py: p.py + ev.clientY - p.sy }));
      }}
      onPointerUp={() => {
        const p = pan.current;
        pan.current = null;
        if (p && !p.moved) onSelect(null);
      }}
    >
      <div className={s.world} style={worldStyle}>
        <svg className={s.edges} width="3400" height="900" aria-hidden="true">
          {geo.map(({ e, g, loop }) => {
            const cls = cx(s.ge, e.fail && s.fail, loop && s.loop, e.bad && s.bad, e.run && s.run, hasRun && !e.run && s.dim, sel('edge', e.id) && s.sel);
            return (
              <g key={e.id}>
                <path className={s['ge-hit']} data-edge={e.id} d={g.d} onClick={() => onSelect({ t: 'edge', k: e.id })} />
                <path className={cls} d={g.d} />
                <path className={cx(cls, s.ga)} d={`M${g.tx - 7} ${g.ty - 4.5} L${g.tx} ${g.ty} L${g.tx - 7} ${g.ty + 4.5} Z`} />
              </g>
            );
          })}
        </svg>
        {geo.map(({ e, g }) =>
          e.label ? (
            <span
              key={`l-${e.id}`}
              className={cx(s.gl, e.fail && s.fail, e.bad && s.bad, e.run && s.run, hasRun && !e.run && s.dim, sel('edge', e.id) && s.sel)}
              style={{ left: `${g.lx.toFixed(1)}px`, top: `${g.ly.toFixed(1)}px` }}
              data-edge={e.id}
              onClick={() => onSelect({ t: 'edge', k: e.id })}
            >
              {e.label}
              {e.max ? <span className={s.glm}> · max {e.max}</span> : null}
            </span>
          ) : null,
        )}
        {nodes.map((n) => (
          <div
            key={n.key}
            className={cx(s.gn, s[`t-${n.category}`], sel('node', n.key) && s.sel, n.bad && s.bad, n.run && s[`run-${n.run}`], hasRun && !n.run && s.dim)}
            style={{ left: `${n.x}px`, top: `${n.y}px` }}
            data-node={n.key}
            role="button"
            tabIndex={-1}
            aria-label={n.name}
            aria-pressed={sel('node', n.key)}
            onClick={() => onSelect({ t: 'node', k: n.key })}
          >
            <Icon k={n.ico} className={s.gi} />
            <div className={s.gt}>
              <div className={s.gnm}>{n.name}</div>
              <div className={s.gsb}>{n.sub}</div>
            </div>
            {n.inPort ? <span className={s.pin} aria-hidden="true" /> : null}
            {n.outPort ? <span className={s.pout} title="Drag to connect" /> : null}
            {n.tag ? <span className={s.gtag}>{n.tag}</span> : null}
            {n.bad ? <span className={s.gbad} title={n.bad}>!</span> : null}
            {n.retry ? <span className={s.gretry}>{n.retry}</span> : null}
            {n.run ? <span className={s.gst}>{n.run === 'ok' ? '✓' : '!'}</span> : null}
          </div>
        ))}
      </div>
      <div className={s.legend} data-ui="1">
        <span><i className={cx(s.lg, s['t-agent'])} />Finance specialist</span>
        <span><i className={cx(s.lg, s['t-policy'])} />Policy check</span>
        <span><i className={cx(s.lg, s['t-checkpoint'])} />Human checkpoint</span>
        <span><i className={cx(s.lg, s['t-action'])} />Action</span>
        <span><i className={s.lgl} />Failure path</span>
      </div>
      <div className={s.zctl} data-ui="1">
        <button type="button" className={s.zb} onClick={() => zoom(1 / 1.2)} aria-label="Zoom out">−</button>
        <button type="button" className={cx(s.zb, s.zp)} onClick={() => zoom(1 / cv.z)} title="Reset to 100%">{Math.round(cv.z * 100)}%</button>
        <button type="button" className={s.zb} onClick={() => zoom(1.2)} aria-label="Zoom in">+</button>
        <button type="button" className={cx(s.zb, s.zf)} onClick={fit}>Fit</button>
      </div>
      <div
        className={s.mm}
        data-mm="1"
        role="img"
        aria-label="Minimap"
        onPointerDown={(ev) => {
          const r = ev.currentTarget.getBoundingClientRect();
          const wx = minX + (ev.clientX - r.left) / ms, wy = minY + (ev.clientY - r.top) / ms;
          setCv((c) => ({ ...c, px: c.w / 2 - wx * c.z, py: c.h / 2 - wy * c.z }));
        }}
      >
        <svg width="188" height="76">
          {nodes.map((n) => (
            <rect key={n.key} className={cx(s.mmn, s[`t-${n.category}`], n.run && s.run, n.bad && s.bad)} x={((n.x - minX) * ms).toFixed(1)} y={((n.y - minY) * ms).toFixed(1)} width={(NW * ms).toFixed(1)} height={(NH * ms).toFixed(1)} rx="1.5" />
          ))}
          <rect className={s.mmv} x={((-cv.px / cv.z - minX) * ms).toFixed(1)} y={((-cv.py / cv.z - minY) * ms).toFixed(1)} width={Math.max(4, (cv.w / cv.z) * ms).toFixed(1)} height={Math.max(4, (cv.h / cv.z) * ms).toFixed(1)} rx="2" />
        </svg>
      </div>
      {children}
    </div>
  );
}
