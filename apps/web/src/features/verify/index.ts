import type { FormField } from "@/features/case/command-forms";
import { CallPanel } from "./CallPanel";
import { IdentityPanel } from "./IdentityPanel";

export { CallPanel, type CallPanelProps } from "./CallPanel";
export { CardholderVerifyPanel } from "./CardholderVerifyPanel";
export { IdentityPanel, type IdentityPanelProps } from "./IdentityPanel";
export type * from "./contract";

/** Case-workspace tabs this feature adds (the integrator decides placement; the prototype shows these inside Communications). */
export const tabs = [
  { key: "identity", label: "Identity verification", Panel: IdentityPanel },
  { key: "call", label: "Verification call", Panel: CallPanel },
] as const;

/**
 * Inputs for this feature's commands (same shape as features/case/command-forms.ts entries).
 * send_verification_request: the panel's channel chooser supplies `channel`; start_callback: the approved
 * questions come from the server's payload_defaults; add_callback_note: the call detail's note field.
 */
export const commandForms: Readonly<Record<string, readonly FormField[]>> = {
  send_verification_request: [
    { name: "channel", label: "Channel (otp or push)", placeholder: "otp" },
  ],
  add_callback_note: [
    { name: "text", label: "Reviewer note", multiline: true },
  ],
};
