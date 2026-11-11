// The one place feature modules are mounted into the case workspace (see registry.ts).
import { CommsPanel, commandForms as commsForms, FollowupTask, isFollowupStep } from '@/features/comms';
import { CallPanel, CardholderVerifyPanel, commandForms as verifyForms, IdentityPanel } from '@/features/verify';
import { useQuery } from '@tanstack/react-query';
import { ApprovalHistory, PacketView } from '@/components/decision';
import { decisionPacketQuery, commandForms as decisionForms, packetProps, ReviewerPanel, VeraRailPanel } from '@/features/decision';
import { commandForms as moneyForms, MONEY_STEPS, MoneyTask } from '@/features/money';
import { COMMAND_FORMS } from './command-forms';
import type { CaseRegistry, CaseRole, CaseSlotProps, RailProps } from './registry';

function MoneyBlock({ caseId, c, onSelectRecord }: CaseSlotProps) {
  return <MoneyTask caseId={caseId} c={c} onOpenRecord={onSelectRecord} />;
}

function CommsTab({ caseId }: CaseSlotProps) {
  return <CommsPanel caseId={caseId} />;
}
function FollowupBlock({ caseId }: CaseSlotProps) {
  return <FollowupTask caseId={caseId} />;
}
// The workspace ActionBar is visible above the tabs, so the verify panels do not repeat the actions.
function IdentityTab({ caseId, onSelectRecord }: CaseSlotProps) {
  return <IdentityPanel caseId={caseId} onOpenSource={onSelectRecord} showActions={false} hideEmpty />;
}
function CallTab({ caseId, onSelectRecord }: CaseSlotProps) {
  return <CallPanel caseId={caseId} onOpenSource={onSelectRecord} showActions={false} hideEmpty />;
}
// Task card while the server offers start_callback: approve (and edit) the questions, record consent, start the call.
function CallTaskBlock({ caseId, onSelectRecord }: CaseSlotProps) {
  return <CallPanel caseId={caseId} onOpenSource={onSelectRecord} />;
}
function CardholderVerifyBlock({ caseId }: CaseSlotProps) {
  return <CardholderVerifyPanel caseId={caseId} />;
}
// Decision tab: the packet stacks under the policy block, only once the server serves one (a 404 says so honestly).
function PacketTab({ c, sel, onSelectRecord }: CaseSlotProps) {
  const packet = useQuery(decisionPacketQuery(c.case_id));
  if (packet.isPending) return null;
  if (!Array.isArray(packet.data?.statements)) return <p style={{ margin: '0 16px 16px', fontSize: 13, color: 'var(--mute)' }}>Decision packet: not available yet.</p>;
  // Read-only packet: the decision actions are the workspace ActionBar's (no second action bar in the tab).
  const p = packetProps(packet.data!);
  return (
    <div data-testid="decision-packet" style={{ padding: '0 16px 16px' }}>
      <PacketView {...p} selected={sel} onSelectRecord={onSelectRecord} />
      <ApprovalHistory items={p.approvals} />
    </div>
  );
}
const REVIEWER_COMMANDS = new Set(['approve_decision', 'return_decision']);
function ReviewerBlock({ c, sel, onSelectRecord }: CaseSlotProps) {
  return <ReviewerPanel c={c} selected={sel} onSelectRecord={onSelectRecord} />;
}
// Vera rail: staff only (the cardholder has no rail).
const railRole = (role: CaseRole | null) => (role === 'analyst' || role === 'reviewer' ? role : null);
function Rail({ c, role, open, onClose, sel, onSelectRecord, onNavigate }: RailProps) {
  const r = railRole(role);
  return r ? <VeraRailPanel c={c} role={r} open={open} onClose={onClose} selected={sel} onSelectRecord={onSelectRecord} onNavigate={onNavigate} /> : null;
}

export const caseRegistry: CaseRegistry = {
  // Communications (prototype): messages, then the identity verification and verification call items.
  tabPanels: [
    { tab: 'comms', key: 'comms', Panel: CommsTab },
    { tab: 'comms', key: 'identity', Panel: IdentityTab },
    { tab: 'comms', key: 'call', Panel: CallTab },
    { tab: 'decision', key: 'packet', Panel: PacketTab },
  ],
  taskBlocks: [
    // Reviewer / card admin with a decision to approve or return (server-offered): the reviewer controls.
    {
      key: 'reviewer',
      match: (c, role) => role === 'reviewer' && [...c.available_actions, ...c.blocked_actions].some((a) => REVIEWER_COMMANDS.has(a.command)),
      Block: ReviewerBlock,
      ownsActions: true,
    },
    // Cardholder "Verify it's you" (step idv): the panel renders the code entry / push approve itself.
    { key: 'verify-cardholder', match: (c, role) => role === 'cardholder' && c.step === 'idv', Block: CardholderVerifyBlock, ownsActions: true },
    // Verification call preparation / retry (analyst): the call panel owns start_callback and its consent box.
    { key: 'call', match: (c, role) => role === 'analyst' && c.available_actions.some((a) => a.command === 'start_callback'), Block: CallTaskBlock, ownsActions: true },
    // Money steps (credit, tracks, dispute, card controls, closure): MoneyTask renders the server's actions itself.
    { key: 'money', match: (c) => MONEY_STEPS.has(c.step), Block: MoneyBlock, ownsActions: true },
    // Follow-up steps (draft → waiting → no response → response): actions stay in the generic ActionBar.
    {
      key: 'followup',
      match: (c) => isFollowupStep(c.step),
      Block: FollowupBlock,
      ownsActions: false,
      ownsTitle: true,
      // In the draft step the block drafts (Draft follow-up) and the draft editor saves and sends itself.
      hides: (c) => (c.step === 'draft' ? ['update_communication_draft', 'send_communication', 'draft_follow_up'] : []),
    },
  ],
  commandForms: { ...COMMAND_FORMS, ...commsForms, ...verifyForms, ...decisionForms, ...moneyForms },
  rail: { Rail, available: (role) => railRole(role) !== null },
};
