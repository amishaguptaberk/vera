"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  caseKey,
  useCaseView,
  useRunCommand,
  useSession,
  type ActionView,
  type CaseView,
} from "@/api";
import { ActionBar } from "@/components/case";
import {
  CallDetail,
  DemoControls,
  type KV,
  type TranscriptLine,
} from "@/components/verify";
import { Button, Skeleton } from "@/design-system/primitives";
import type {
  CallbackDetail,
  CallLine,
  CallOutcome,
  CallQuestion,
} from "./contract";
import {
  CALL_EFFECT,
  CALL_FACT,
  CALL_HEADLINE,
  CALL_STATUS,
  isOutcome,
  time,
} from "./labels";
import {
  callbackDetailQuery,
  callbacksQuery,
  errorText,
  setNextCallOutcome,
} from "./queries";
import styles from "./verify.module.css";

export type CallPanelProps = {
  caseId: string;
  /** A specific call; omitted = the latest call, or the call preparation when the server offers `start_callback`. */
  callbackId?: string;
  onOpenSource?: (id: string) => void;
  onBack?: () => void;
  showActions?: boolean;
};

const DEMO_OUTCOMES: readonly [CallOutcome, string][] = [
  ["confirmed", "Confirmed"],
  ["contradicted", "Contradicted"],
  ["voicemail", "Voicemail"],
  ["no_answer", "No answer"],
  ["incomplete", "Incomplete"],
];

export function transcriptLines(
  lines: readonly CallLine[],
  contact: string,
): TranscriptLine[] {
  return lines.map((l) => ({
    key: l.seq,
    who:
      l.speaker === "agent"
        ? "Vera"
        : l.speaker === "contact"
          ? contact
          : "System",
    text:
      l.speaker === "agent" || l.speaker === "contact" ? `“${l.text}”` : l.text,
    system: l.speaker !== "agent" && l.speaker !== "contact",
  }));
}

/** Pure mapping of a call detail to the presentational props (shared by the panel and the dev preview). */
export function callView(k: CallbackDetail) {
  const live = k.status === "in_progress";
  const outcome = isOutcome(k.status) ? k.status : null;
  const qText = new Map(k.questions.map((q) => [q.id, q.text]));
  const rows: KV[] = [
    { k: "Authorized by", v: `${k.approved_by} · ${time(k.created_at)}` },
    { k: "Attempt", v: String(k.attempt) },
    {
      k: "Status",
      v: live
        ? `${CALL_STATUS.in_progress} · started ${time(k.created_at)}`
        : (CALL_STATUS[k.status as keyof typeof CALL_STATUS] ?? k.status),
    },
  ];
  const r = k.result;
  const result =
    !live && outcome
      ? {
          headline: CALL_HEADLINE[outcome],
          rows: r
            ? [
                {
                  k: "Result",
                  v: r.result === "confirmed" ? "Confirmed" : "Failed",
                },
                { k: "Outcome", v: CALL_STATUS[r.outcome] },
                { k: "Authorization answer", v: r.authorization_answer ?? "—" },
                ...r.answers.map((a) => ({
                  k: qText.get(a.question_id) ?? a.question_id,
                  v: `${a.answer} · line ${a.line_seq}`,
                })),
              ]
            : [],
          effect: [
            { k: "Fact status", v: CALL_FACT[outcome] },
            { k: "Policy effect", v: CALL_EFFECT[outcome] },
          ],
        }
      : null;
  return {
    live,
    rows,
    result,
    title: live ? "Call in progress" : "Verification call complete",
  };
}

function Bar({
  c,
  onAction,
  busy,
}: {
  c: CaseView;
  onAction: (a: ActionView) => void;
  busy: string | null;
}) {
  return (
    <ActionBar
      actions={c.available_actions}
      blocked={c.blocked_actions}
      busy={busy}
      onAction={onAction}
    />
  );
}

function DemoOutcome() {
  const session = useSession();
  const [picked, setPicked] = useState<string | null>(null);
  if (session.data?.environment !== "synthetic") return null;
  return (
    <DemoControls
      label={`Synthetic demo · next call outcome${picked ? ` · ${picked}` : ""}`}
    >
      {DEMO_OUTCOMES.map(([k, label]) => (
        <Button
          key={k}
          variant={["sm", "demo"]}
          onClick={() =>
            void setNextCallOutcome(k).then((o) => setPicked(o.outcome))
          }
        >
          {label}
        </Button>
      ))}
    </DemoControls>
  );
}

export function CallPanel({
  caseId,
  callbackId,
  onOpenSource,
  onBack,
  showActions = true,
}: CallPanelProps) {
  const cv = useCaseView(caseId);
  const list = useQuery(callbacksQuery(caseId));
  const latest = list.data?.length ? list.data[list.data.length - 1] : null;
  const id = callbackId ?? latest?.id ?? null;
  const detail = useQuery({
    ...callbackDetailQuery(caseId, id ?? ""),
    enabled: !!id,
  });
  const run = useRunCommand(caseId);
  const qc = useQueryClient();
  const [note, setNote] = useState("");

  const c = cv.data;
  const busy = run.isPending ? (run.variables?.action.command ?? null) : null;
  const contact = c?.cardholder.name ?? "Cardholder";
  const phone = c?.cardholder.contact_on_file.phone_masked;
  const startAction =
    c?.available_actions.find((a) => a.command === "start_callback") ?? null;

  if (list.isPending || (id && detail.isPending))
    return (
      <div aria-busy="true">
        <Skeleton height={120} />
      </div>
    );
  if (list.isError)
    return (
      <p className={styles.rd}>
        {errorText(list.error, "Verification calls are not available yet.")}
      </p>
    );

  const onAction = (a: ActionView) => {
    if (!c) return;
    const payload =
      a.command === "start_callback"
        ? {
            questions:
              (a.payload_defaults.questions as CallQuestion[] | undefined) ??
              [],
          }
        : {};
    run.mutate({ action: a, caseVersion: c.case_version, payload });
  };
  const bar =
    showActions && c ? <Bar c={c} onAction={onAction} busy={busy} /> : null;

  // Preparation: no call yet (or a retry is offered and no call selected) — approve the exact questions.
  if (!id && startAction) {
    const qs = (
      (startAction.payload_defaults.questions as CallQuestion[] | undefined) ??
      []
    ).map((q) => q.text);
    return (
      <>
        <CallDetail
          title="Verification call"
          idLabel="Proposed"
          target={
            phone
              ? {
                  text: `${contact} · ${phone}`,
                  recordId:
                    (startAction.payload_defaults.target_record_id as
                      string | undefined) ?? "Contact on file",
                  field: "phone",
                }
              : null
          }
          rows={[{ k: "Status", v: "Proposed · waiting for your approval" }]}
          questionsLabel="Questions the call will ask"
          questions={qs}
          transcript={null}
          noTranscriptText="Not started."
          sources={[]}
          onOpenSource={onOpenSource}
          actions={bar}
          onBack={onBack}
        />
        <DemoOutcome />
      </>
    );
  }
  if (!id) return <p className={styles.rd}>No messages or calls yet.</p>;
  if (detail.isError)
    return (
      <p className={styles.rd}>
        {errorText(detail.error, "Call detail is not available yet.")}
      </p>
    );
  const k = detail.data as CallbackDetail;
  const { live, rows, result } = callView(k);
  const canNote =
    c?.available_actions.find(
      (a) => a.command === "add_callback_note" && a.enabled,
    ) ?? null;
  return (
    <>
      <CallDetail
        title={callView(k).title}
        idLabel={k.id}
        live={live}
        target={{
          text: phone ? `${contact} · ${phone}` : contact,
          recordId: k.target_record_id,
          field: k.target_field,
        }}
        rows={rows}
        questionsLabel="Questions asked"
        questions={k.questions.map((q) => q.text)}
        transcript={transcriptLines(k.transcript, contact)}
        noTranscriptText={
          live
            ? "Dialing…"
            : "Transcript unavailable. A structured result can’t be recorded until the call is reviewed."
        }
        result={result}
        notes={
          result && canNote && c
            ? {
                value: note,
                onChange: setNote,
                canSave: note.trim().length > 0,
                busy: busy === "add_callback_note",
                saved: k.notes.length
                  ? `Saved · ${k.notes.length} ${k.notes.length === 1 ? "note" : "notes"}`
                  : "",
                onSave: () =>
                  run.mutate(
                    {
                      action: canNote,
                      caseVersion: c.case_version,
                      payload: { callback_id: k.id, text: note.trim() },
                    },
                    {
                      onSuccess: () => {
                        setNote("");
                        void qc.invalidateQueries({
                          queryKey: caseKey(caseId),
                        });
                      },
                    },
                  ),
              }
            : null
        }
        sources={[k.id, k.target_record_id]}
        onOpenSource={onOpenSource}
        actions={!live ? bar : null}
        onBack={onBack}
      />
      {!live && startAction ? <DemoOutcome /> : null}
    </>
  );
}
