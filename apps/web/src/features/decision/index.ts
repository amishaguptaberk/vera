// Decision packet, reviewer view and Vera rail (VER-012-F7, VER-012-F9). Mounting instructions: README.md.
import { DecisionPanel } from './DecisionPanel';

export { commandForms } from './command-forms';
export type { AskCitation, AskResponse, DecisionPacket } from './contract';
export { DecisionPanel, packetProps, type DecisionPanelProps } from './DecisionPanel';
export { decisionPacketQuery, useAsk } from './queries';
export { addPair, signatureOf, type RailPair } from './rail-state';
export { ReviewerPanel, type ReviewerPanelProps } from './ReviewerPanel';
export { SUGGESTED, VeraRailPanel, pairMessages, workMessages, type VeraRailPanelProps } from './VeraRailPanel';
export { VeraButton } from '@/components/decision';

/** Case-workspace tabs this feature provides (replaces the inline DecisionPanel in CaseWorkspace.tsx). */
export const tabs = [{ key: 'decision', label: 'Decision', Panel: DecisionPanel }] as const;
export { previewStates } from './preview';
