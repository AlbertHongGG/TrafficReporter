import type { AiEvidenceResponse, AiEvidenceSessionState } from '../../../shared/contracts';

const cloneSerializable = <T,>(value: T): T => {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
};

export const DEFAULT_AI_EVIDENCE_JOB_STATE: AiEvidenceSessionState['job'] = {
  status: 'idle',
  progress: 0,
  stage: '',
  detail: '',
  requestId: null,
  error: null,
  startedAt: null,
  stageStartedAt: null,
  updatedAt: null,
  currentToolName: null,
};

function cloneAiEvidenceResult(result: AiEvidenceResponse | null) {
  return result ? cloneSerializable(result) : null;
}

export function buildDefaultAiEvidenceState(overrides: Partial<AiEvidenceSessionState> = {}): AiEvidenceSessionState {
  return {
    prompt: overrides.prompt ?? '',
    job: {
      ...DEFAULT_AI_EVIDENCE_JOB_STATE,
      ...(overrides.job ? cloneSerializable(overrides.job) : {}),
    },
    result: cloneAiEvidenceResult(overrides.result ?? null),
    lastCompletedAt: overrides.lastCompletedAt ?? null,
  };
}