/**
 * AI evidence analysis-request use-cases (Phase 4-B).
 *
 * Pure extraction of `beginAiRequest` + `handleRunAiEvidence` from
 * `useAiEvidenceWorkflow`: validate the prompt/asset, open a tracked
 * request, call the infra API, then land the result
 * (`setLprRuntimeStatus` + `setAiResult` + completed job + projection) or
 * record the failure (failed job + feedback). Stale completions — a
 * superseded request finishing late — apply nothing.
 */
import type { LprVehicleKind } from '../../../../platform/ipc/bindings';
import type { OutputCompressionMode } from '../../../export/domain/model';
import { getLprSessionByFileId } from '../../domain/analysisState';
import type {
  AiEvidenceRequest,
  AiEvidenceResponse,
} from '../../domain/aiEvidenceState';
import type { VideoMarkerRect } from '../../domain/model';
import { aiErr, aiOk, defaultAiPorts } from './aiEvidencePorts.usecase';
import type {
  AiEvidencePorts,
  AiEvidenceResult,
} from './aiEvidencePorts.usecase';
import { runAiEvidenceJobUpdate } from './aiEvidenceJob.usecase';
import { runAiEvidenceProjection } from './aiEvidenceProjection.usecase';

export interface AiEvidenceBeginInput {
  fileId: string;
  prompt: string;
}

export interface AiEvidenceBeginData {
  fileId: string;
  requestId: string;
}

/**
 * Open a tracked AI evidence request: validate the prompt, register the
 * active request, reset prompt/result state, and mark the job running.
 */
export function runAiEvidenceBegin(
  input: AiEvidenceBeginInput,
  ports: AiEvidencePorts = defaultAiPorts,
): AiEvidenceResult<AiEvidenceBeginData> {
  const trimmedPrompt = input.prompt.trim();
  if (!trimmedPrompt) {
    const message = 'AI evidence analysis requires a natural-language description.';
    ports.notifyFeedback(message);
    return aiErr(message);
  }
  const requestId = ports.createRequestId();
  ports.setActiveRequest({ requestId, fileId: input.fileId });
  ports.actions.setAiPrompt(input.fileId, trimmedPrompt);
  ports.actions.setAiResult(input.fileId, null);
  runAiEvidenceJobUpdate(
    {
      fileId: input.fileId,
      job: {
        status: 'running',
        progress: 0.05,
        stage: 'Prepare',
        detail: 'Preparing AI evidence workflow.',
        requestId,
        error: null,
        startedAt: ports.now(),
        progressKind: 'host-step',
        toolName: null,
        toolLabel: null,
        stepIndex: 1,
        stepCount: 11,
        stageStepIndex: 1,
        stageStepCount: 1,
      },
    },
    ports,
  );
  ports.notifyFeedback(null);
  return aiOk({ fileId: input.fileId, requestId });
}

export interface AiEvidenceCompleteInput {
  fileId: string;
  requestId: string;
  response: AiEvidenceResponse;
}

export interface AiEvidenceCompleteData {
  applied: boolean;
}

/**
 * Land a successful analysis response. Stale responses (`applied: false`)
 * change nothing.
 */
export function runAiEvidenceComplete(
  input: AiEvidenceCompleteInput,
  ports: AiEvidencePorts = defaultAiPorts,
): AiEvidenceResult<AiEvidenceCompleteData> {
  const active = ports.getActiveRequest();
  if (active === null || active.requestId !== input.requestId || active.fileId !== input.fileId) {
    return aiOk({ applied: false });
  }
  const response = input.response;
  ports.actions.setLprRuntimeStatus(response.runtime);
  ports.actions.setAiResult(input.fileId, response);
  runAiEvidenceJobUpdate(
    {
      fileId: input.fileId,
      job: {
        status: 'completed',
        progress: 1,
        stage: 'Completed',
        detail: response.summary,
        error: null,
        requestId: input.requestId,
        progressKind: 'host-step',
        toolName: null,
        toolLabel: null,
        stepIndex: 11,
        stepCount: 11,
        stageStepIndex: 1,
        stageStepCount: 1,
      },
    },
    ports,
  );
  runAiEvidenceProjection({ fileId: input.fileId, response }, ports);
  ports.clearActiveRequest(input.requestId);
  return aiOk({ applied: true });
}

export interface AiEvidenceFailInput {
  fileId: string;
  requestId: string;
  error: unknown;
}

export interface AiEvidenceFailData {
  applied: boolean;
  error: string | null;
}

/**
 * Record an analysis failure on the job and surface feedback.
 * Stale failures (`applied: false`) change nothing.
 */
export function runAiEvidenceFail(
  input: AiEvidenceFailInput,
  ports: AiEvidencePorts = defaultAiPorts,
): AiEvidenceResult<AiEvidenceFailData> {
  const active = ports.getActiveRequest();
  if (active === null || active.requestId !== input.requestId || active.fileId !== input.fileId) {
    return aiOk({ applied: false, error: null });
  }
  ports.logError('AI evidence analysis failed.', input.error);
  const summary = ports.describeError(input.error, 'Unable to run the AI evidence workflow.');
  runAiEvidenceJobUpdate(
    {
      fileId: input.fileId,
      job: {
        status: 'failed',
        progress: 1,
        stage: 'Failed',
        detail: 'AI evidence analysis failed.',
        error: summary,
        requestId: input.requestId,
        progressKind: 'host-step',
        toolName: null,
        toolLabel: null,
        stepIndex: 11,
        stepCount: 11,
        stageStepIndex: 1,
        stageStepCount: 1,
      },
    },
    ports,
  );
  ports.notifyFeedback(summary);
  ports.clearActiveRequest(input.requestId);
  return aiOk({ applied: true, error: summary });
}

export interface AiEvidenceAnalysisInput {
  fileId: string;
  sourcePath: string;
  assetReady: boolean;
  prompt: string;
  markerRect: VideoMarkerRect | null;
  compressionMode: OutputCompressionMode;
  audioBitrateKbps?: number | null;
  targetVehicleKind?: LprVehicleKind | null;
}

export interface AiEvidenceAnalysisData {
  fileId: string;
  requestId: string;
  applied: boolean;
}

/**
 * Full analysis orchestration: begin → infra analyze → complete/fail.
 * Returns `ok: false` when the run never started (asset not ready, blank
 * prompt) or when the run failed; stale completions report `applied: false`.
 */
export async function runAiEvidenceAnalysis(
  input: AiEvidenceAnalysisInput,
  ports: AiEvidencePorts = defaultAiPorts,
): Promise<AiEvidenceResult<AiEvidenceAnalysisData>> {
  if (!input.assetReady) {
    return aiErr('AI evidence analysis requires a ready media asset.');
  }
  const begun = runAiEvidenceBegin({ fileId: input.fileId, prompt: input.prompt }, ports);
  if (!begun.ok) {
    return begun;
  }
  const requestId = begun.data.requestId;
  const lprSession = getLprSessionByFileId(ports.readAnalysis(), input.fileId);
  const request: AiEvidenceRequest = {
    sourcePath: input.sourcePath,
    description: input.prompt.trim(),
    markerRect: input.markerRect,
    compressionMode: input.compressionMode,
    audioBitrateKbps: input.audioBitrateKbps ?? null,
    targetVehicleKind: input.targetVehicleKind ?? 'any',
    countryHints: lprSession.countryHints,
    analysisProfileId: lprSession.selectedAnalysisProfileId,
    enableDeveloperDiagnostics: lprSession.showDeveloperDiagnostics,
    requestId,
  };
  try {
    const response = await ports.analyze(request);
    const completed = runAiEvidenceComplete({ fileId: input.fileId, requestId, response }, ports);
    if (!completed.ok) {
      return completed;
    }
    return aiOk({ fileId: input.fileId, requestId, applied: completed.data.applied });
  } catch (error) {
    const failed = runAiEvidenceFail({ fileId: input.fileId, requestId, error }, ports);
    if (!failed.ok) {
      return failed;
    }
    const summary = failed.data.error
      ?? ports.describeError(error, 'Unable to run the AI evidence workflow.');
    return aiErr(summary);
  }
}
