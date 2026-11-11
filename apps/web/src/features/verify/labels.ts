// Copy for identity and call states, ported from the prototype (Main.dc.html comms list / cm.call).
import type { CallOutcome, CallStatus, IdentityStatus } from "./contract";

export const time = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
      })
    : "";

export const IDENTITY_STATUS: Record<IdentityStatus, string> = {
  requested: "Awaiting cardholder",
  verified: "Identity verified",
  expired: "Verification expired",
  cancelled: "Request cancelled",
  failed: "Verification failed",
  declined: "Verification denied",
};

export const IDENTITY_NEXT: Record<IdentityStatus, string> = {
  requested: "Waiting for the cardholder",
  verified: "Verification call can start",
  failed: "Send a targeted follow-up or reassign",
  declined: "Use another approved method or hold",
  expired: "Send a new request or use a follow-up",
  cancelled: "Send a new request or use a follow-up",
};

export const CHANNEL: Record<"otp" | "push", { label: string; sub: string }> = {
  otp: { label: "Phone on file", sub: "Text message to the phone on file" },
  push: {
    label: "Ramp app notification",
    sub: "Push to the signed-in card app",
  },
};

export const CALL_STATUS: Record<CallStatus, string> = {
  queued: "Queued",
  ringing: "Ringing",
  completed: "Completed",
  failed: "Call failed",
  busy: "Line busy",
  timed_out: "Timed out",
  in_progress: "In progress",
  confirmed: "Completed · confirmed",
  contradicted: "Completed · not confirmed",
  voicemail: "Unanswered · voicemail",
  no_answer: "Unanswered · no answer",
  incomplete: "Incomplete · result not recorded",
};

export const CALL_HEADLINE: Record<CallOutcome, string> = {
  confirmed: "Cardholder confirmed the answers to the approved questions.",
  contradicted:
    "Cardholder’s answers don’t confirm the report. Verification failed · credit remains blocked.",
  voicemail: "No answer reached voicemail. No result recorded · retry or hold.",
  no_answer: "No answer. No result recorded · retry or hold.",
  incomplete:
    "The call ended before the questions were answered. No result recorded · retry or hold.",
};

export const CALL_FACT: Record<CallOutcome, string> = {
  confirmed: "Structured verification · corroborates, doesn’t decide",
  contradicted: "Structured verification · does not confirm the report",
  voicemail: "No structured result",
  no_answer: "No structured result",
  incomplete: "No structured result",
};

export const CALL_EFFECT: Record<CallOutcome, string> = {
  confirmed: "Credit eligibility re-evaluated by the Policy Controller",
  contradicted: "Verification failed · credit remains blocked",
  voicemail: "No change · retry or hold",
  no_answer: "No change · retry or hold",
  incomplete: "No change · retry or hold",
};

export const isOutcome = (s: string): s is CallOutcome => s in CALL_HEADLINE;

/** Provider label: always say plainly when a call is simulated. */
export const providerLabel = (p: string | null | undefined): string | null =>
  p === "simulated"
    ? "Simulated call"
    : p === "elevenlabs"
      ? "Live voice call"
      : null;

/** Defensive: keep only the last 4 digits of anything that looks like a phone number. */
export const maskNumber = (n: string): string => {
  const digits = n.replace(/\D/g, "");
  if (digits.length <= 4) return n;
  return `•••• ${digits.slice(-4)}`;
};

export const elapsed = (from: string, now: number): string => {
  const s = Math.max(0, Math.floor((now - Date.parse(from)) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
