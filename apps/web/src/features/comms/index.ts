import { CommsPanel } from './CommsPanel';

export { CommsDraft, CommsPanel } from './CommsPanel';
export { FOLLOWUP_STEPS, FollowupTask, isFollowupStep } from './FollowupTask';
export { RequestPage } from './RequestPage';
export { commandForms } from './command-forms';
export * from './contract';
export { communicationsKey, communicationKey, requestKey, useCardholderRequest, useCommunication, useCommunications, useMyRequests, useSubmitResponse } from './queries';

/** Case-workspace tabs this feature adds (the prototype's "Communications" tab). */
export const tabs = [{ key: 'comms', label: 'Communications', Panel: CommsPanel }] as const;
