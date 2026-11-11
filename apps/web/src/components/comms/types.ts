// Presentational props for the communications screens. Labels are pre-computed by the feature layer from server data.

export type CommsTone = 'ok' | 'bad' | 'cur' | 'wait' | 'mute';

export type CommsListRow = { id: string; kind: string; title: string; status: string; tone: CommsTone; at: string };

export type KV = { k: string; v: string };

/** One server-offered action, as the feature passes it down (label/enabled/blocked reason from the server). */
export type CommsAction = { command: string; label: string; enabled: boolean; blockedReason?: string | null; ghost?: boolean };

export type MessageResponse = { meta: string; text: string; isNew: boolean; kv: readonly KV[] };
