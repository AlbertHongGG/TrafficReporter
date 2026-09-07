/**
 * AI evidence projection use-case (Phase 4-B).
 *
 * Pure extraction of `applyAiEvidenceProjection` from
 * `useAiEvidenceWorkflow`: fold an `AiEvidenceResponse` into the file's LPR
 * session (target-track fallback chain, anchor resolution, history append)
 * and dispatch `replaceLprSession`. Deterministic given the same analysis
 * snapshot and response; the only effects are the ports action + id/time
 * factories.
 */
import { getLprSessionByFileId } from '../../domain/analysisState';
import { buildDefaultLprState, buildLprTargetAnchor } from '../../domain/lprState';
import { buildAiEvidenceProjectionDetail } from '../../domain/lprWorkflowHelpers';
import type { AiEvidenceResponse } from '../../domain/aiEvidenceState';
import type { LprTargetTrack } from '../../domain/lprState';
import { aiOk, defaultAiPorts } from './aiEvidencePorts.usecase';
import type {
  AiEvidencePorts,
  AiEvidenceResult,
} from './aiEvidencePorts.usecase';

export interface AiEvidenceProjectionInput {
  fileId: string;
  response: AiEvidenceResponse;
}

export interface AiEvidenceProjectionData {
  selectedTargetTrackId: string | null;
  acceptedCandidateId: string | null;
  workflowMode: string;
}

/**
 * Project an AI evidence response onto the LPR session and persist it.
 */
export function runAiEvidenceProjection(
  input: AiEvidenceProjectionInput,
  ports: AiEvidencePorts = defaultAiPorts,
): AiEvidenceResult<AiEvidenceProjectionData> {
  const currentLprState = getLprSessionByFileId(ports.readAnalysis(), input.fileId);
  const response = input.response;
  const acceptedCandidateId = response.projection.acceptedCandidateId ?? null;
  const projectedTargetTracks = response.projection.targetTracks;
  const selectedTargetTrackId = response.projection.selectedTargetTrackId
    ?? response.targetSelection?.selectedTrackId
    ?? response.projection.analysisTrack?.id
    ?? currentLprState.selectedTargetTrackId;
  const projectedSelectedTrack = projectedTargetTracks.find(
    (track: LprTargetTrack) => track.id === selectedTargetTrackId,
  ) ?? null;
  const selectedTargetAnchor = projectedSelectedTrack
    ? buildLprTargetAnchor(
      projectedSelectedTrack,
      response.primaryAnchor?.timeMs ?? currentLprState.selectedTargetAnchor?.timeMs ?? null,
    )
    : response.projection.analysisTrack
      ? buildLprTargetAnchor(
        response.projection.analysisTrack,
        response.primaryAnchor?.timeMs ?? response.projection.interval?.startMs ?? null,
      )
      : currentLprState.selectedTargetAnchor;
  const projectionDetail = buildAiEvidenceProjectionDetail(
    response.projection.candidates,
    response.projection.review,
    projectedTargetTracks,
  );
  const timestamp = ports.now();
  const hasCandidates = response.projection.candidates.length > 0;
  const workflowMode = hasCandidates ? 'review' : 'target';
  const projectedSession = buildDefaultLprState({
    ...currentLprState,
    workflowMode,
    interval: response.projection.interval ?? currentLprState.interval,
    targetTracks: projectedTargetTracks,
    selectedTargetTrackId,
    selectedTargetAnchor,
    analysisTrack: response.projection.analysisTrack ?? null,
    samples: response.projection.samples,
    candidates: response.projection.candidates,
    review: response.projection.review ?? null,
    lastAnalysisProvenance: response.projection.provenance ?? null,
    decision: response.projection.decision ?? null,
    acceptedCandidateId,
    job: {
      ...currentLprState.job,
      status: 'completed',
      progress: 1,
      stage: 'AI evidence',
      detail: projectionDetail,
      requestId: response.requestId ?? currentLprState.job.requestId,
      error: null,
      updatedAt: timestamp,
    },
    history: hasCandidates
      ? [...currentLprState.history, {
        id: ports.createHistoryId(),
        createdAt: timestamp,
        interval: response.projection.interval ?? null,
        targetTrackId: selectedTargetTrackId ?? response.projection.analysisTrack?.id ?? null,
        acceptedCandidateId,
        analysisProfileId: currentLprState.selectedAnalysisProfileId,
        developerDiagnosticsEnabled: currentLprState.showDeveloperDiagnostics,
        candidates: response.projection.candidates,
        summary: response.summary,
      }]
      : currentLprState.history,
  });
  ports.actions.replaceLprSession(input.fileId, projectedSession);
  return aiOk({ selectedTargetTrackId, acceptedCandidateId, workflowMode });
}
