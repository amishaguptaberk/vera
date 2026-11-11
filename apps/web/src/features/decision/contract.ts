// Data this feature needs from the server. Written from the VER-009 brief and Vera_Handoff §3.2/§3.4 while
// services/api/vera_api/decisions.py was still being built; optional fields tolerate both shapes.

/** One citation in an ask answer: selecting it selects the cited record. */
export type AskCitation = { record_id: string; version?: number | null; field?: string | null };

/** A server-offered button on an answer (registry command or navigation). Never auto-run. */
export type AskAction = { label: string; command?: string | null; nav?: string | null };

/** `POST /api/cases/{id}/ask` → read-only, canned answer. */
export type AskResponse = {
  answer: string;
  citations: AskCitation[];
  refused: boolean;
  intent?: string | null;
  title?: string | null;
  paragraphs?: string[] | null;
  actions?: AskAction[] | null;
  /** Server dedup key (Handoff §3.4). When absent the client keys on the server's answer + citations, never the question text. */
  signature?: string | null;
};

export type AskRequest = { text: string; role: string; last_intent?: string | null };

/** A section of the decision packet (summary, evidence comparison, policy result, recommendation, versions). */
export type PacketSection = { key: string; label: string; value: string; record_ids?: string[] | null };

export type PolicyRule = { label: string; passed: boolean; record_ids?: string[] | null };

/** `GET /api/cases/{id}/decision-packet?version=` */
export type DecisionPacket = {
  case_id: string;
  version: number;
  snapshot_hash?: string | null;
  policy_version?: number | null;
  workflow_version?: number | null;
  /** packet_status fact, e.g. `draft` | `sent` | `approved` | `returned` | `stale`. */
  status?: string | null;
  approval_status?: string | null;
  /** True when evidence changed after the packet was built; the server decides. */
  stale?: boolean | null;
  stale_reason?: string | null;
  sections: PacketSection[];
  citations?: string[] | null;
  policy?: { label: string; rules?: PolicyRule[] | null } | null;
  return_reason?: string | null;
  approvals?: { id: string; status: string; reviewer?: string | null; at?: string | null; reason?: string | null }[] | null;
};
