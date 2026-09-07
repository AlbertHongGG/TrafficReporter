/**
 * LPR interval (range) analysis use-case (Phase 4-A, extracted from `useLprWorkflow`).
 *
 * Pure function: validates the interval/target/anchor preconditions from the
 * session snapshot (dispatching the same failed-job + feedback updates as the
 * hook), calls the infra interval API, decides store dispatches, and returns
 * a unified result.
 */
import { resolveLprAnalysisTargetVehicleKind } from '../../domain/lprState';
import {
  buildLprCompletionDetail,
  isAnchorWithinInterval,
  normalizeLprInterval,
} from '../../domain/lprWorkflowHelpers';
import {
  INTERACTIVE_RANGE_LATENCY_BUDGET_MS,
  resolveLprRangeAnalysisIntent,
} from '../lprAnalysisIntent';
import {
  commitLprJobUpdate,
  defaultLprPorts,
  lprErr,
  lprOk,
  lprSkipped,
  lprStaleError,
  lprValidationError,
  parseCountryHints,
  readReadyFile,
  toLprUsecaseError,
  type LprPorts,
  type LprResult,
} from './lprPorts.usecase';

export interface LprAnalyzeIntervalInput {
  /** Unsaved country-hint draft (null falls back to the session hints). */
  countryHintDraft: string | null;
}

export interface LprAnalyzeIntervalData {
  requestId: string;
  candidateCount: number;
  detail: string;
}

function failPrecondition(
  ports: LprPorts,
  detail: string,
  errorMessage: string,
): LprResult<LprAnalyzeIntervalData> {
  commitLprJobUpdate(ports, {
    status: 'failed',
    progress: 1,
    stage: 'Interval',
    detail,
    error: errorMessage,
  });
  ports.notifyFeedback(errorMessage);
  return lprErr(lprValidationError(errorMessage, null, 'analyze_lpr_interval'));
}

export async function runLprAnalyzeInterval(
  input: LprAnalyzeIntervalInput,
  ports: LprPorts = defaultLprPorts,
): Promise<LprResult<LprAnalyzeIntervalData>> {
  const file = readReadyFile(ports);
  if (!file) {
    return lprErr(lprSkipped('No ready media file for interval analysis.', 'analyze_lpr_interval'));
  }

  const session = ports.readLprSession();

  if (!session.interval) {
    return failPrecondition(
      ports,
      'Range analysis requires an explicit interval.',
      'Set Clip, In, or Out before running Range.',
    );
  }

  const selectedTrack = session.targetTracks.find(
    (track) => track.id === session.selectedTargetTrackId,
  ) ?? null;
  if (!selectedTrack) {
    return failPrecondition(
      ports,
      'Range analysis requires a current target selection.',
      'Select a target before running Range.',
    );
  }

  const interval = normalizeLprInterval(session.interval);
  const anchor = session.selectedTargetAnchor;
  if (!anchor) {
    return failPrecondition(
      ports,
      'Range analysis requires an anchored target selection.',
      'Select a target on the intended frame before running Range.',
    );
  }

  if (!isAnchorWithinInterval(anchor.timeMs, interval)) {
    return failPrecondition(
      ports,
      'Range analysis requires the selected target anchor to stay inside the chosen interval.',
      'The selected target frame is outside the current Range. Reselect the target on a frame inside the interval, or adjust In/Out.',
    );
  }

  const countryHints = parseCountryHints(
    input.countryHintDraft ?? session.countryHints.join(', '),
  );
  ports.actions.setLprCountryHints(countryHints);

  const durationMs = Math.max(0, interval.endMs - interval.startMs);
  const analysisIntent = resolveLprRangeAnalysisIntent(durationMs, session.useDenseSampling);
  const analysisVehicleKind = resolveLprAnalysisTargetVehicleKind(selectedTrack, session.targetVehicleKind);

  const requestId = ports.beginRequest('Interval', 'Tracking the selected target across the chosen interval.', 0.12);

  try {
    const response = await ports.analyzeInterval({
      sourcePath: file.asset.path,
      interval,
      anchorTimeMs: Math.max(0, Math.round(anchor.timeMs)),
      targetVehicleKind: analysisVehicleKind,
      selectedTargetBox: anchor.box,
      selectedTargetTrackId: selectedTrack.id,
      countryHints,
      analysisIntent,
      latencyBudgetMs: INTERACTIVE_RANGE_LATENCY_BUDGET_MS,
      analysisProfileId: session.selectedAnalysisProfileId,
      enableDeveloperDiagnostics: session.showDeveloperDiagnostics,
      requestId,
    });

    if (ports.isStale(requestId)) {
      ports.forgetRequest(requestId);
      return lprErr(lprStaleError(requestId, 'analyze_lpr_interval'));
    }

    const intervalDetail = response.jobStatus === 'degraded'
      ? response.summary
      : (buildLprCompletionDetail(response.candidates, response.review) ?? response.summary);
    ports.actions.setLprRuntimeStatus(response.runtime);
    ports.actions.setLprInterval(interval);
    ports.actions.setLprAnalysisTrack(response.analysisTrack ?? response.targetTracks[0] ?? null);
    ports.actions.setLprSamples(response.samples);
    ports.actions.setLprCandidates(response.candidates);
    ports.actions.setLprReview(response.review ?? null);
    ports.actions.setLprProvenance(response.provenance ?? null);
    ports.actions.setLprDecision(response.decision ?? null);
    ports.actions.appendLprHistory({
      id: ports.createHistoryId(),
      createdAt: ports.now(),
      interval,
      targetTrackId: response.analysisTrack?.id ?? selectedTrack.id,
      acceptedCandidateId: response.acceptedCandidateId ?? null,
      analysisProfileId: session.selectedAnalysisProfileId,
      developerDiagnosticsEnabled: session.showDeveloperDiagnostics,
      candidates: response.candidates,
      summary: intervalDetail,
    });
    ports.actions.setLprMode(response.candidates.length > 0 ? 'review' : 'target');
    commitLprJobUpdate(ports, {
      status: response.jobStatus ?? 'completed',
      progress: 1,
      stage: 'Interval',
      detail: intervalDetail,
      reasonCode: response.tracking?.degradedReason ?? null,
      trackingTier: response.tracking?.trackingTier ?? null,
      coverageRatio: response.tracking?.coverageRatio ?? null,
    });
    ports.forgetRequest(requestId);
    return lprOk({ requestId, candidateCount: response.candidates.length, detail: intervalDetail });
  } catch (error) {
    if (ports.isStale(requestId)) {
      ports.forgetRequest(requestId);
      return lprErr(lprStaleError(requestId, 'analyze_lpr_interval'));
    }
    ports.logError('Range analysis failed.', error);
    const summary = ports.describeError(error, 'Unable to analyze the selected interval.');
    commitLprJobUpdate(ports, {
      status: 'failed',
      progress: 1,
      stage: 'Interval',
      detail: 'Interval analysis failed.',
      error: summary,
      reasonCode: 'interval-analysis-failed',
    });
    ports.notifyFeedback(summary);
    ports.forgetRequest(requestId);
    return lprErr(toLprUsecaseError(error, 'analyze_lpr_interval', 'Unable to analyze the selected interval.', 'interval-analysis-failed'));
  }
}
