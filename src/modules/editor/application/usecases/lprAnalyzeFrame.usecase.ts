/**
 * LPR frame-analysis use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: resolves the selected target box + vehicle kind from the
 * session snapshot, calls the infra frame API, decides store dispatches, and
 * returns a unified result. Stale (superseded/cancelled) completions dispatch
 * nothing, mirroring the hook's silent-ignore semantics.
 */
import { findClosestTrackFrame } from '../../domain/model';
import {
  buildLprCompletionDetail,
} from '../../domain/lprWorkflowHelpers';
import {
  resolveLprAnalysisTargetVehicleKind,
} from '../../domain/lprState';
import {
  commitLprJobUpdate,
  defaultLprPorts,
  lprErr,
  lprOk,
  lprSkipped,
  lprStaleError,
  parseCountryHints,
  readReadyFile,
  toLprUsecaseError,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';

export interface LprAnalyzeFrameInput {
  /** Live playhead in ms (owned by the hook's ref; not read from the store). */
  playheadMs: number;
  /** Unsaved country-hint draft (null falls back to the session hints). */
  countryHintDraft: string | null;
}

export interface LprAnalyzeFrameData {
  requestId: string;
  candidateCount: number;
  detail: string;
}

export async function runLprAnalyzeFrame(
  input: LprAnalyzeFrameInput,
  ports: LprPorts = defaultLprPorts,
): Promise<LprResult<LprAnalyzeFrameData>> {
  const file = readReadyFile(ports);
  if (!file) {
    return lprErr(lprSkipped('No ready media file for frame analysis.', 'analyze_lpr_frame'));
  }

  const session = ports.readLprSession();
  const countryHints = parseCountryHints(
    input.countryHintDraft ?? session.countryHints.join(', '),
  );
  ports.actions.setLprCountryHints(countryHints);

  const selectedTrack = session.targetTracks.find(
    (track) => track.id === session.selectedTargetTrackId,
  ) ?? null;
  const analysisVehicleKind = resolveLprAnalysisTargetVehicleKind(selectedTrack, session.targetVehicleKind);
  const selectedTargetBox = selectedTrack
    ? findClosestTrackFrame(selectedTrack, input.playheadMs, ports.overlayToleranceMs)?.box ?? null
    : null;

  const requestId = ports.beginRequest('Frame', 'Analyzing the current frame.', 0.24);

  try {
    const response = await ports.analyzeFrame({
      sourcePath: file.asset.path,
      timeMs: Math.max(0, Math.round(input.playheadMs)),
      markerRect: file.markerRect,
      targetVehicleKind: analysisVehicleKind,
      selectedTargetBox,
      countryHints,
      analysisProfileId: session.selectedAnalysisProfileId,
      enableDeveloperDiagnostics: session.showDeveloperDiagnostics,
      requestId,
    });

    if (ports.isStale(requestId)) {
      ports.forgetRequest(requestId);
      return lprErr(lprStaleError(requestId, 'analyze_lpr_frame'));
    }

    const detail = buildLprCompletionDetail(response.candidates, response.review);
    ports.actions.setLprRuntimeStatus(response.runtime);
    ports.actions.setLprAnalysisTrack(null);
    ports.actions.setLprSamples(response.sample ? [response.sample] : []);
    ports.actions.setLprCandidates(response.candidates);
    ports.actions.setLprReview(response.review ?? null);
    ports.actions.setLprProvenance(response.provenance ?? null);
    ports.actions.setLprDecision(response.decision ?? null);
    if (response.candidates.length > 0) {
      ports.actions.appendLprHistory({
        id: ports.createHistoryId(),
        createdAt: ports.now(),
        interval: null,
        targetTrackId: response.detections[0]?.id ?? null,
        acceptedCandidateId: response.acceptedCandidateId ?? null,
        analysisProfileId: session.selectedAnalysisProfileId,
        developerDiagnosticsEnabled: session.showDeveloperDiagnostics,
        candidates: response.candidates,
        summary: detail,
      });
    }
    commitLprJobUpdate(ports, {
      status: response.jobStatus ?? 'completed',
      progress: 1,
      stage: 'Frame',
      detail,
      reasonCode: null,
      trackingTier: null,
      coverageRatio: null,
    });
    ports.forgetRequest(requestId);
    return lprOk({ requestId, candidateCount: response.candidates.length, detail });
  } catch (error) {
    if (ports.isStale(requestId)) {
      ports.forgetRequest(requestId);
      return lprErr(lprStaleError(requestId, 'analyze_lpr_frame'));
    }
    ports.logError('Frame analysis failed.', error);
    const summary = ports.describeError(error, 'Unable to analyze the current frame.');
    commitLprJobUpdate(ports, {
      status: 'failed',
      progress: 1,
      stage: 'Frame',
      detail: 'Frame analysis failed.',
      error: summary,
      reasonCode: 'frame-analysis-failed',
    });
    ports.notifyFeedback(summary);
    ports.forgetRequest(requestId);
    return lprErr(toLprUsecaseError(error, 'analyze_lpr_frame', 'Unable to analyze the current frame.', 'frame-analysis-failed'));
  }
}
