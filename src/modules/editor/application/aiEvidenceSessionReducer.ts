import type { AiEvidenceJobState, AiEvidenceResponse, AiEvidenceSessionState } from '../domain/model';
import { buildDefaultAiEvidenceState } from '../domain/aiEvidenceState';

export type AiEvidenceSessionAction =
  | { type: 'set-ai-prompt'; fileId: string; prompt: string }
  | { type: 'set-ai-job'; fileId: string; job: Partial<AiEvidenceJobState> }
  | { type: 'set-ai-result'; fileId: string; result: AiEvidenceResponse | null }
  | { type: 'reset-ai-session'; fileId: string };

const AI_EVIDENCE_ACTION_TYPES = new Set<AiEvidenceSessionAction['type']>([
  'set-ai-prompt',
  'set-ai-job',
  'set-ai-result',
  'reset-ai-session',
]);

export function isAiEvidenceSessionAction(action: { type: string }): action is AiEvidenceSessionAction {
  return AI_EVIDENCE_ACTION_TYPES.has(action.type as AiEvidenceSessionAction['type']);
}

export function reduceAiEvidenceSession(
  aiState: AiEvidenceSessionState,
  action: AiEvidenceSessionAction,
): AiEvidenceSessionState {
  switch (action.type) {
    case 'set-ai-prompt':
      return {
        ...aiState,
        prompt: action.prompt,
      };

    case 'set-ai-job':
      return {
        ...aiState,
        job: {
          ...aiState.job,
          ...action.job,
        },
      };

    case 'set-ai-result':
      return {
        ...aiState,
        result: action.result ? buildDefaultAiEvidenceState({ result: action.result }).result : null,
        lastCompletedAt: action.result ? new Date().toISOString() : aiState.lastCompletedAt,
      };

    case 'reset-ai-session':
      return buildDefaultAiEvidenceState();
  }
}