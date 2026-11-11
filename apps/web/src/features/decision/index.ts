// Decision packet, reviewer view and Vera rail. Mounted into the case workspace by features/case/mounts.tsx.
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
