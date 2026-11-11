"use client";

// Development preview: every prototype state in this feature's scope, rendered with the REAL presentational
// components and the panels' own mapping functions, fed by ./dev-fixtures (imported ONLY here). Commands are no-ops.
import type { ReactNode } from "react";
import { ActionBar } from "@/components/case";
import { CallDetail, CardholderVerify } from "@/components/verify";
import { callView, transcriptLines } from "./CallPanel";
import { IdentityBody } from "./IdentityPanel";
import type { CallOutcome, IdentityStatus } from "./contract";
import {
  ACTIONS,
  callFixture,
  HOLDER,
  idv,
  OUTBOX,
  PHONE,
  QUESTIONS,
} from "./dev-fixtures/chg-1042";

const noop = () => {};
const meta = [
  "Bayline Industrial Supply · $2,840.00",
  "Card ending 4418 · Posted Nov 8",
];
const chText =
  "Finance is reviewing the $2,840.00 Bayline Industrial Supply charge and needs to confirm it’s you before calling. This doesn’t decide anything about the charge.";

const identity = (
  status: IdentityStatus | null,
  actions = ACTIONS.active,
  channel: "otp" | "push" = "otp",
) =>
  function IdentityPreview() {
    return (
      <IdentityBody
        v={status ? idv(status, { channel }) : null}
        holder={HOLDER}
        actions={actions}
        blocked={[]}
        busy={null}
        onAction={noop}
        channel={channel}
        onChannel={noop}
        now={Date.now()}
        onOpenSource={noop}
        onBack={noop}
      />
    );
  };

const callState = (
  status: CallOutcome | "in_progress",
  shown?: number,
  actions = ACTIONS.callfail,
) =>
  function CallPreview() {
    const k = callFixture(status, shown);
    const view = callView(k);
    return (
      <CallDetail
        title={view.title}
        idLabel={k.id}
        live={view.live}
        target={{
          text: `${HOLDER} · ${PHONE}`,
          recordId: k.target_record_id,
          field: k.target_field,
        }}
        rows={view.rows}
        questionsLabel="Questions asked"
        questions={k.questions.map((q) => q.text)}
        transcript={transcriptLines(k.transcript, "Priya")}
        result={view.result}
        notes={
          view.result
            ? { value: "", onChange: noop, onSave: noop, canSave: false }
            : null
        }
        sources={[k.id, "REP-1042", "CHG-1042"]}
        onOpenSource={noop}
        actions={
          view.live ? null : (
            <ActionBar
              actions={status === "confirmed" ? [] : actions}
              blocked={[]}
              onAction={noop}
            />
          )
        }
        onBack={noop}
      />
    );
  };

const cardholder = (
  channel: "otp" | "push",
  done?: "verified" | "failed",
  message?: string,
) =>
  function CardholderPreview() {
    return (
      <CardholderVerify
        heading={
          done
            ? done === "verified"
              ? "You’re verified"
              : "Verification not completed"
            : "Verify your identity"
        }
        meta={meta}
        channel={channel}
        text={chText}
        demo={
          channel === "otp" ? { label: OUTBOX.label, code: OUTBOX.code } : null
        }
        value=""
        onChange={noop}
        onSubmit={noop}
        onApprove={noop}
        onDeny={noop}
        expiry="Expires in 9 minutes"
        message={message}
        done={
          done === "verified"
            ? {
                title: "Thanks — you’re verified.",
                text: "Sam Rivera from Finance may call the number on file to ask about the charge. Finance will never ask you for a code on the call.",
              }
            : done
              ? {
                  title: "Verification didn’t complete.",
                  text: "Nothing about your charge was decided. Finance will contact you through the number or email on file.",
                }
              : null
        }
      />
    );
  };

export const previewStates: { name: string; render: () => ReactNode }[] = [
  {
    name: "Identity · choose channel (no request yet)",
    render: identity(null, ACTIONS.send),
  },
  {
    name: "Identity · request sent, awaiting cardholder (resend cooldown)",
    render: identity("requested"),
  },
  {
    name: "Identity · push sent, awaiting cardholder",
    render: identity("requested", ACTIONS.active, "push"),
  },
  {
    name: "Cardholder · enter code (synthetic demo phone)",
    render: cardholder("otp"),
  },
  {
    name: "Cardholder · incorrect code",
    render: cardholder(
      "otp",
      undefined,
      "That code didn’t match. 2 attempts left.",
    ),
  },
  { name: "Cardholder · approve or deny push", render: cardholder("push") },
  { name: "Cardholder · verified", render: cardholder("otp", "verified") },
  {
    name: "Cardholder · verification not completed",
    render: cardholder("push", "failed"),
  },
  { name: "Identity · verified", render: identity("verified", []) },
  {
    name: "Identity · failed (no attempts left)",
    render: identity("failed", ACTIONS.failed),
  },
  { name: "Identity · expired", render: identity("expired", ACTIONS.send) },
  {
    name: "Identity · denied",
    render: identity("declined", ACTIONS.send, "push"),
  },
  { name: "Identity · cancelled", render: identity("cancelled", ACTIONS.send) },
  {
    name: "Call · preparation (approve exact questions)",
    render: () => (
      <CallDetail
        title="Verification call"
        idLabel="Proposed"
        target={{
          text: `${HOLDER} · ${PHONE}`,
          recordId: "PRF-4418",
          field: "phone",
        }}
        rows={[{ k: "Status", v: "Proposed · waiting for your approval" }]}
        questionsLabel="Questions the call will ask"
        questions={QUESTIONS.map((q) => q.text)}
        transcript={null}
        noTranscriptText="Not started."
        sources={[]}
        actions={
          <ActionBar actions={ACTIONS.call} blocked={[]} onAction={noop} />
        }
        onBack={noop}
      />
    ),
  },
  {
    name: "Call · in progress (transcript appearing)",
    render: callState("in_progress", 3),
  },
  { name: "Call · confirmed", render: callState("confirmed") },
  {
    name: "Call · contradicted (call failed step)",
    render: callState("contradicted"),
  },
  {
    name: "Call · voicemail (call failed step)",
    render: callState("voicemail"),
  },
  {
    name: "Call · no answer (call failed step)",
    render: callState("no_answer"),
  },
  {
    name: "Call · incomplete (call failed step)",
    render: callState("incomplete"),
  },
];
