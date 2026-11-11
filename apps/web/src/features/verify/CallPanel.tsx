"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
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
import {
  callStatusOf,
  isActiveCall,
  type CallAnswer,
  type CallbackDetail,
  type CallLine,
  type CallOutcome,
  type CallQuestion,
} from "./contract";
import {
  CALL_EFFECT,
  CALL_FACT,
  CALL_HEADLINE,
  CALL_STATUS,
  elapsed,
  isOutcome,
  maskNumber,
  providerLabel,
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
  /** Inside the Communications tab: render nothing (not a second empty line) when there is nothing yet. */
  hideEmpty?: boolean;
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
  const v = k.voice ?? null;
  const live = isActiveCall(k.status) || (!!v && isActiveCall(v.call_status));
  const outcome = isOutcome(k.status) ? k.status : null;
  const shownStatus = live && v ? v.call_status : k.status;
  const startedAt = v?.started_at ?? k.started_at ?? k.created_at;
  const qText = new Map(k.questions.map((q) => [q.id, q.text]));
  const rows: KV[] = [
    { k: "Authorized by", v: `${k.approved_by_name ?? k.approved_by} · ${time(k.created_at)}` },
    { k: "Attempt", v: String(k.attempt) },
    {
      k: "Status",
      v: live
        ? `${CALL_STATUS[shownStatus as keyof typeof CALL_STATUS] ?? shownStatus} · started ${time(startedAt)}`
        : (CALL_STATUS[k.status as keyof typeof CALL_STATUS] ?? k.status),
    },
  ];
  const purpose = v?.purpose ?? k.purpose;
  if (purpose) rows.unshift({ k: "Purpose", v: purpose });
  if (k.approval_state) rows.splice(1, 0, { k: "Approval", v: k.approval_state });
  const vAnswers = v?.structured_answers ?? [];
  const r =
    k.result ??
    (v && vAnswers.length
      ? { result: callStatusOf(k), answers: [] as CallAnswer[] }
      : null);
  const confidence = v?.confidence ?? r?.confidence ?? k.confidence;
  const legacy =
    !!outcome && !vAnswers.length && !r?.answers.some((a) => a.cited_lines);
  const result =
    !live && (outcome || r)
      ? {
          headline: outcome
            ? CALL_HEADLINE[outcome]
            : (CALL_STATUS[k.status as keyof typeof CALL_STATUS] ?? k.status),
          rows: r
            ? [
                {
                  k: "Result",
                  v:
                    r.result === "confirmed"
                      ? "Confirmed"
                      : r.result === "failed"
                        ? "Failed"
                        : r.result,
                },
                ...(r.outcome
                  ? [{ k: "Outcome", v: CALL_STATUS[r.outcome] }]
                  : []),
                ...(r.authorization_answer !== undefined
                  ? [
                      {
                        k: "Authorization answer",
                        v: r.authorization_answer ?? "—",
                      },
                    ]
                  : []),
                ...(confidence != null
                  ? [{ k: "Confidence", v: String(confidence) }]
                  : []),
                ...(legacy
                  ? r.answers.map((a) => ({
                      k: qText.get(a.question_id) ?? a.question_id,
                      v: `${a.answer} · line ${a.line_seq}`,
                    }))
                  : []),
              ]
            : [],
          answers: legacy
            ? []
            : vAnswers.length
              ? vAnswers.map((a) => ({
                  question: qText.get(a.question_id) ?? a.question_id,
                  answer: a.answer,
                  lines: [a.line_index],
                }))
              : (r?.answers ?? []).map((a) => ({
                question: qText.get(a.question_id) ?? a.question_id,
                answer: a.answer,
                lines:
                  a.cited_lines ?? (a.line_seq != null ? [a.line_seq] : []),
              })),
          effect: outcome
            ? [
                { k: "Fact status", v: CALL_FACT[outcome] },
                { k: "Policy effect", v: CALL_EFFECT[outcome] },
              ]
            : [],
        }
      : null;
  return {
    live,
    rows,
    result,
    provider: providerLabel(v?.provider ?? k.provider),
    masked: v?.masked_number ?? k.masked_number ?? null,
    startedAt,
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
  // start_callback is rendered next to its consent checkbox instead.
  return (
    <ActionBar
      actions={c.available_actions.filter((a) => a.command !== "start_callback")}
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
  hideEmpty = false,
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
  const [consent, setConsent] = useState(false);
  // The analyst's edits to the server's proposed questions, by index (ids stay the server's).
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [now, setNow] = useState(() => Date.now());
  const active =
    !!detail.data &&
    (isActiveCall(detail.data.status) ||
      isActiveCall(callStatusOf(detail.data)));
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);

  const c = cv.data;
  const busy = run.isPending ? (run.variables?.action.command ?? null) : null;
  const contact = c?.cardholder.name ?? "Cardholder";
  const phoneRaw = c?.cardholder.contact_on_file.phone_masked;
  const startAction =
    c?.available_actions.find((a) => a.command === "start_callback") ?? null;
  const approved = (
    (startAction?.payload_defaults.questions as CallQuestion[] | undefined) ?? []
  ).map((q, i) => ({ ...q, text: edits[i] ?? q.text }));

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
            ...a.payload_defaults,
            questions: approved,
            consent_recorded: consent,
          }
        : a.command === "end_callback" || a.command === "escalate_callback"
          ? { ...a.payload_defaults, callback_id: id }
          : {};
    run.mutate(
      { action: a, caseVersion: c.case_version, payload },
      {
        onSuccess: () => {
          if (a.command === "start_callback") {
            setConsent(false);
            setEdits({});
          }
        },
      },
    );
  };
  const startButton =
    showActions && c && startAction ? (
      <div className={styles.row}>
        <Button
          variant="sm"
          onClick={() => onAction(startAction)}
          disabled={
            !consent || !startAction.enabled || busy === "start_callback"
          }
          title={
            !startAction.enabled
              ? (startAction.blocked_reason ?? undefined)
              : undefined
          }
        >
          {startAction.label}
        </Button>
      </div>
    ) : null;
  const consentBox =
    showActions && startAction
      ? { checked: consent, onChange: setConsent }
      : null;
  const bar =
    showActions && c ? (
      <>
        {startButton}
        <Bar c={c} onAction={onAction} busy={busy} />
      </>
    ) : null;

  // Preparation: no call yet (or a retry is offered and no call selected) — approve the exact questions.
  if (!id && startAction) {
    const qs = approved.map((q) => q.text);
    const d = startAction.payload_defaults;
    const masked = (d.masked_number as string | undefined) ?? phoneRaw;
    const prepRows: KV[] = [];
    if (typeof d.purpose === "string")
      prepRows.push({ k: "Purpose", v: d.purpose });
    prepRows.push({
      k: "Approval",
      v:
        typeof d.approval_state === "string"
          ? d.approval_state
          : "Proposed · waiting for your approval",
    });
    const prov = providerLabel(d.provider as string | undefined);
    return (
      <>
        <CallDetail
          title="Verification call"
          idLabel="Proposed"
          target={
            masked
              ? {
                  text: `${contact} · ${maskNumber(masked)}`,
                  recordId:
                    (startAction.payload_defaults.target_record_id as
                      string | undefined) ?? "Contact on file",
                  field: "phone",
                }
              : null
          }
          rows={prepRows}
          provider={prov}
          consent={consentBox}
          editQuestions={
            showActions
              ? { onChange: (i, text) => setEdits((e) => ({ ...e, [i]: text })) }
              : null
          }
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
  if (!id) return hideEmpty ? null : <p className={styles.rd}>No messages or calls yet.</p>;
  if (detail.isError)
    return (
      <p className={styles.rd}>
        {errorText(detail.error, "Call detail is not available yet.")}
      </p>
    );
  const k = detail.data as CallbackDetail;
  const view = callView(k);
  const { live, rows, result, provider } = view;
  const masked = view.masked ?? phoneRaw;
  const canNote =
    c?.available_actions.find(
      (a) => a.command === "add_callback_note" && a.enabled,
    ) ?? null;
  return (
    <>
      <CallDetail
        title={view.title}
        idLabel={k.id}
        live={live}
        target={{
          text: masked ? `${contact} · ${maskNumber(masked)}` : contact,
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
        provider={provider}
        elapsed={live ? elapsed(view.startedAt, now) : null}
        consent={!live ? consentBox : null}
        actions={bar}
        onBack={onBack}
      />
      {!live && startAction ? <DemoOutcome /> : null}
    </>
  );
}
