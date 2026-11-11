// Presentation only: canvas positions for workflow nodes, keyed by node id. Positions are the prototype's
// G3() coordinates (x = 40 + 220·column) mapped onto the API's v3 node keys. The API graph has a parallel
// branch after intake (charge + related investigators) and an identity step the prototype did not have;
// those are placed in the same grid. Unknown nodes fall back to an automatic layered layout.
import type { Graph } from './contract';

const GX = (c: number) => 40 + 220 * c;

export const LAYOUT: Record<string, { x: number; y: number }> = {
  intake: { x: GX(0), y: 300 },
  charge_investigator: { x: GX(1.5), y: 210 },
  related_transaction_investigator: { x: GX(1.5), y: 390 },
  receipt_document_reviewer: { x: GX(3), y: 300 },
  pc1: { x: GX(4), y: 300 },
  identity_verification: { x: GX(5), y: 110 },
  live_verification: { x: GX(6), y: 110 },
  cardholder_follow_up: { x: GX(5), y: 490 },
  await_cardholder_response: { x: GX(6), y: 490 },
  decision_packet_preparer: { x: GX(7), y: 300 },
  retry_within_limits: { x: GX(7), y: 640 },
  analyst_decision: { x: GX(8), y: 300 },
  pc2: { x: GX(9), y: 300 },
  reviewer_approval: { x: GX(10), y: 300 },
  credit_executor: { x: GX(11), y: 300 },
  dispute_packet_preparer: { x: GX(13), y: 200 },
  prevention_planner: { x: GX(12), y: 400 },
  analyst_handoff: { x: GX(12), y: 640 },
  admin_approval: { x: GX(13), y: 400 },
  final_communication: { x: GX(14), y: 300 },
  close_or_monitor: { x: GX(15), y: 300 },
};

/** Explicit lanes for back edges and long jumps (prototype `lane` values), keyed `source>target:outcome`. */
export const LANES: Record<string, number> = {
  'await_cardholder_response>receipt_document_reviewer:response': 600,
  'reviewer_approval>decision_packet_preparer:rejected': 22,
  'analyst_decision>final_communication:authorized': 160,
  'final_communication>retry_within_limits:send failed': 790,
  'analyst_handoff>close_or_monitor:close unresolved': 704,
  'retry_within_limits>cardholder_follow_up:retry': 760,
  'pc1>analyst_handoff:contradictory': 820,
};

/** Positions for every node: the table, else a layered layout by BFS depth from the trigger. */
export function layoutGraph(graph: Graph): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  const depth: Record<string, number> = {};
  const trigger = graph.nodes.find((n) => n.kind === 'trigger')?.key;
  if (trigger) {
    depth[trigger] = 0;
    const q = [trigger];
    while (q.length) {
      const k = q.shift()!;
      for (const e of graph.edges) {
        if (e.source === k && depth[e.target] === undefined) {
          depth[e.target] = depth[k] + 1;
          q.push(e.target);
        }
      }
    }
  }
  const perCol: Record<number, number> = {};
  for (const n of graph.nodes) {
    const fixed = LAYOUT[n.key];
    if (fixed) {
      out[n.key] = fixed;
      continue;
    }
    const d = depth[n.key] ?? 0;
    const i = (perCol[d] = (perCol[d] ?? 0) + 1);
    out[n.key] = { x: GX(d), y: 760 + 140 * i };
  }
  return out;
}
