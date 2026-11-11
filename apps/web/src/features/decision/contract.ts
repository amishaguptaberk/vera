// Data this feature needs from the server (backend: services/api/vera_api/decisions.py).
// Optional fields are read only when present.

/** One citation in an ask answer: selecting it selects the cited record. */
export type AskCitation = { record_id: string; version: number; field: string };

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
  /** Server dedup key. When absent the client keys on the server's answer + citations, never the question text. */
  signature?: string | null;
};

/** The request carries only `{text}`; the server classifies intent. */
export type AskRequest = { text: string };

/** A record version (and field) a packet statement cites (backend Citation). */
export type PacketCitation = { record_id: string; version: number; field?: string | null };
/** Packet statement: a claim with the records it cites (backend PacketStatement). */
export type PacketStatement = { text: string; citations: PacketCitation[] };

/** Server PolicyView as stored in the packet summary. */
export type PacketPolicy = { label: string; status?: string; policy_version?: number; rules_failed?: string[]; evidence_used?: string[] };

export type ApprovalView = {
  approval_id: string;
  case_id: string;
  packet_version: number;
  policy_version: number;
  workflow_version: number;
  status: string;
  reviewer_id: string;
  return_reason?: string | null;
  return_next_step?: string | null;
  return_owner_id?: string | null;
};

/** `GET /api/cases/{id}/decision-packet?version=` (DecisionPacketView). 404 `packet_not_found` = no packet yet. */
export type DecisionPacket = {
  case_id: string;
  version: number;
  latest_version: number;
  /** False when the case's evidence snapshot moved on (stale). */
  current: boolean;
  snapshot_hash: string;
  workflow_version: number;
  policy_version: number;
  policy_evaluation_id: number | null;
  statements: PacketStatement[];
  open_conflicts: Record<string, unknown>[];
  missing: string[];
  policy: PacketPolicy | null;
  recommendation: string;
  decision: string | null;
  approval: ApprovalView | null;
  created_by: string;
  created_at: string;
};
