/**
 * AI evidence job-tracking use-cases (Phase 4-B).
 *
 * Pure extraction of the job duties of `useAiEvidenceWorkflow`:
 * `updateAiJob` (stamped job patch), the `editor/ai-evidence-progress`
 * event mapping (stale-guarded), and `handleCancelAiJob` (cancel flow).
 * Each use-case calls infra through ports, dispatches store actions through
 * ports, and returns a unified {@link AiEvidenceResult}.
 */
import { getAiEvidenceSessionByFileId } from '../../domain/analysisState';
import { resolveStageStartedAt } from '../../domain/lprWorkflowHelpers';
import type {
  AiEvidenceJobState,
  AiEvidenceProgress,
} from '../../domain/aiEvidenceState';
import { aiOk, defaultAiPorts } from './aiEvidencePorts.usecase';
import type {
  AiEvidencePorts,
  AiEvidenceResult,
} from './aiEvidencePorts.usecase';

export interface AiEvidenceJobUpdateInput {
  fileId: string;
  job: Partial<AiEvidenceJobState>;
}

export interface AiEvidenceJobUpdateData {
  fileId: string;
}

/**
 * Stamp a job patch (`stageStartedAt` clock + `updatedAt`) against the
 * current session job and dispatch `setAiJob`.
 */
export function runAiEvidenceJobUpdate(
  input: AiEvidenceJobUpdateInput,
  ports: AiEvidencePorts = defaultAiPorts,
): AiEvidenceResult<AiEvidenceJobUpdateData> {
  const currentJob = getAiEvidenceSessionByFileId(ports.readAnalysis(), input.fileId).job;
  const timestamp = ports.now();
  ports.actions.setAiJob(input.fileId, {
    ...input.job,
    stageStartedAt: resolveStageStartedAt(currentJob, input.job, timestamp),
    updatedAt: timestamp,
  });
  return aiOk({ fileId: input.fileId });
}

export interface AiEvidenceProgressInput {
  fileId: string;
  requestId: string;
  progress: AiEvidenceProgress;
}

export interface AiEvidenceProgressData {
  applied: boolean;
}

/**
 * Map one `editor/ai-evidence-progress` event onto the active job.
 * Events for a superseded or unknown request are ignored (`applied: false`)
 * with no side effects.
 */
export function runAiEvidenceProgress(
  input: AiEvidenceProgressInput,
  ports: AiEvidencePorts = defaultAiPorts,
): AiEvidenceResult<AiEvidenceProgressData> {
  const active = ports.getActiveRequest();
  if (active === null || active.requestId !== input.requestId || active.fileId !== input.fileId) {
    return aiOk({ applied: false });
  }
  const event = input.progress;
  runAiEvidenceJobUpdate(
    {
      fileId: active.fileId,
      job: {
        status: event.failed ? 'failed' : event.done ? 'completed' : 'running',
        progress: Math.max(0, Math.min(1, event.progress)),
        stage: event.stage,
        detail: event.detail,
        requestId: active.requestId,
        error: event.failed ? event.detail : null,
        progressKind: event.progressKind ?? null,
        toolName: event.toolName ?? null,
        toolLabel: event.toolLabel ?? null,
        stepIndex: event.stepIndex ?? null,
        stepCount: event.stepCount ?? null,
        stageStepIndex: event.stageStepIndex ?? null,
        stageStepCount: event.stageStepCount ?? null,
      },
    },
    ports,
  );
  return aiOk({ applied: true });
}

export interface AiEvidenceCancelInput {
  /** Stage label used when the current job has no stage yet. */
  stageFallback?: string | null;
}

export interface AiEvidenceCancelData {
  cancelled: boolean;
}

/**
 * Cancel the active AI evidence request: mark cancelling, ask the runtime
 * to cancel, then mark cancelled and refresh the runtime status.
 * With no active request this is a no-op (`cancelled: false`).
 * A cancel failure is recorded on the job and returned as `ok: false`.
 */
export async function runAiEvidenceCancel(
  input: AiEvidenceCancelInput = {},
  ports: AiEvidencePorts = defaultAiPorts,
): Promise<AiEvidenceResult<AiEvidenceCancelData>> {
  const active = ports.getActiveRequest();
  if (active === null) {
    return aiOk({ cancelled: false });
  }
  const stageFallback = input.stageFallback ?? 'AI evidence';
  const currentStage = getAiEvidenceSessionByFileId(ports.readAnalysis(), active.fileId).job.stage
    || stageFallback;
  runAiEvidenceJobUpdate(
    {
      fileId: active.fileId,
      job: {
        status: 'cancelled',
        stage: currentStage,
        detail: 'Cancelling current AI evidence task.',
        error: null,
      },
    },
    ports,
  );
  try {
    await ports.cancelJob();
    ports.clearActiveRequest(active.requestId);
    runAiEvidenceJobUpdate(
      {
        fileId: active.fileId,
        job: {
          status: 'cancelled',
          progress: 1,
          stage: currentStage,
          detail: 'Current AI evidence task cancelled.',
          error: null,
        },
      },
      ports,
    );
    await ports.refreshRuntimeStatus();
    return aiOk({ cancelled: true });
  } catch (error) {
    const summary = ports.describeError(error, 'Unable to cancel the current AI evidence task.');
    runAiEvidenceJobUpdate(
      {
        fileId: active.fileId,
        job: {
          status: 'failed',
          progress: 1,
          stage: currentStage,
          detail: 'Unable to cancel the current AI evidence task.',
          error: summary,
        },
      },
      ports,
    );
    ports.notifyFeedback(summary);
    return { ok: false, error: summary };
  }
}
