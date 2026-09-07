/**
 * LPR workflow hook — React glue (Blueprint §4, Phase 4-D).
 *
 * Slim surface: subscribes to the workspace snapshot via props, derives the
 * LPR view-model, and forwards UI events to the LPR use-cases through
 * `LprPorts` (`notifyFeedback` overridden with the workspace feedback
 * callback; request tracking, clock, and store dispatch stay on the
 * production defaults). All business decisions live in
 * `usecases/lpr*.usecase.ts`; the `editor/lpr-progress` subscription lives
 * in `useLprProgressListener` (invoked in place below).
 */
import { useCallback, useMemo, useRef } from 'react';
import type { EditorWorkspaceState, EditorFileState } from '../domain/model';
import { getLprSessionByFileId } from '../domain/analysisState';
import { resolveLprAnalysisTargetVehicleKind } from '../domain/lprState';
import { promptLprEvidenceSavePath } from '../infrastructure/dialog';
import { resolveLprDisplayCandidate } from './plateWindow';
import type {
  LprSessionState,
  LprTargetTrack,
  TimelineIntervalSelection,
} from '../domain/model';
import { defaultLprEvidenceFileName } from '../domain/mediaNamingHelpers';
import { useLprProgressListener } from './useLprProgressListener';
import {
  commitLprJobUpdate,
  defaultLprPorts,
  type LprPorts,
} from './usecases/lprPorts.usecase';
import { runLprScanTargets } from './usecases/lprScanTargets.usecase';
import { runLprAnalyzeFrame } from './usecases/lprAnalyzeFrame.usecase';
import { runLprAnalyzeInterval } from './usecases/lprAnalyzeInterval.usecase';
import { runLprCancelJob } from './usecases/lprCancelJob.usecase';
import { runLprRefreshRuntimeStatus } from './usecases/lprRuntimeStatus.usecase';
import { runLprSelectTargetTrack } from './usecases/lprTargetSelection.usecase';
import { runLprApplyCountryHints } from './usecases/lprCountryHints.usecase';
import {
  runLprSetIntervalBoundary,
  runLprUseClipInterval,
  suggestLprInterval,
} from './usecases/lprIntervalEditing.usecase';
import { runLprExportEvidence } from './usecases/lprExportEvidence.usecase';

export interface UseLprWorkflowOptions {
  state: EditorWorkspaceState;
  activeFile: EditorFileState | null | undefined;
  livePlayheadMsRef: React.MutableRefObject<number>;
  currentIsPlaying: boolean;
  setWorkspaceFeedback: (message: string | null) => void;
}

export function useLprWorkflow({
  state,
  activeFile,
  livePlayheadMsRef,
  // `currentIsPlaying` stays on `UseLprWorkflowOptions` for signature
  // stability; the pause-on-select decision lives in the target-selection
  // use-case (via `ports.readIsPlaying`).
  setWorkspaceFeedback,
}: UseLprWorkflowOptions) {
  const latestCountryHintDraftRef = useRef<string | null>(null);

  const lprPorts = useMemo<LprPorts>(() => ({
    ...defaultLprPorts,
    notifyFeedback: (message) => {
      setWorkspaceFeedback(message);
    },
  }), [setWorkspaceFeedback]);

  const lprRuntimeStatus = state.analysis.lprRuntimeStatus;
  const lprState = useMemo(() => getLprSessionByFileId(state.analysis, activeFile?.id ?? null), [activeFile?.id, state.analysis]);
  const lprJob = lprState.job;
  const lprBusy = lprJob.status === 'queued' || lprJob.status === 'running';
  const lprSelectedTargetAnchor = lprState.selectedTargetAnchor;
  const lprSelectedTrack = useMemo(
    () => lprState.targetTracks.find((track: LprTargetTrack) => track.id === lprState.selectedTargetTrackId) ?? null,
    [lprState.selectedTargetTrackId, lprState.targetTracks],
  );
  const lprAnalysisTrack = lprState.analysisTrack;
  const lprTopCandidate = useMemo(
    () => resolveLprDisplayCandidate(lprState.candidates, lprState.review, lprState.acceptedCandidateId),
    [lprState.acceptedCandidateId, lprState.candidates, lprState.review],
  );
  const lprAnalysisVehicleKind = useMemo(
    () => resolveLprAnalysisTargetVehicleKind(lprSelectedTrack, lprState.targetVehicleKind),
    [lprSelectedTrack, lprState.targetVehicleKind],
  );
  const canAnalyzeRange = Boolean(activeFile && !lprBusy && lprSelectedTrack && lprSelectedTargetAnchor && lprState.interval);

  const refreshLprRuntimeStatus = useCallback(async () => {
    await runLprRefreshRuntimeStatus(lprPorts);
  }, [lprPorts]);

  const updateLprJob = useCallback((job: Partial<LprSessionState['job']>) => {
    commitLprJobUpdate(lprPorts, job);
  }, [lprPorts]);

  const handleCancelLprJob = useCallback(async () => {
    await runLprCancelJob(lprPorts);
  }, [lprPorts]);

  const applyCountryHints = useCallback((draftValue: string) => {
    const result = runLprApplyCountryHints({ draft: draftValue }, lprPorts);
    return result.ok ? result.data.countryHints : [];
  }, [lprPorts]);

  const resolveSuggestedInterval = useCallback((playheadMs: number): TimelineIntervalSelection => (
    suggestLprInterval({ playheadMs }, lprPorts)
  ), [lprPorts]);

  const handleSetIntervalBoundary = useCallback((boundary: 'start' | 'end') => {
    runLprSetIntervalBoundary({ playheadMs: livePlayheadMsRef.current, boundary }, lprPorts);
  }, [livePlayheadMsRef, lprPorts]);

  const handleUseClipInterval = useCallback(() => {
    runLprUseClipInterval({ playheadMs: livePlayheadMsRef.current }, lprPorts);
  }, [livePlayheadMsRef, lprPorts]);

  const handleScanLprTargets = useCallback(async () => {
    await runLprScanTargets({ playheadMs: livePlayheadMsRef.current }, lprPorts);
  }, [livePlayheadMsRef, lprPorts]);

  const handleAnalyzeLprFrame = useCallback(async () => {
    await runLprAnalyzeFrame({
      playheadMs: livePlayheadMsRef.current,
      countryHintDraft: latestCountryHintDraftRef.current,
    }, lprPorts);
  }, [livePlayheadMsRef, lprPorts]);

  const handleAnalyzeLprInterval = useCallback(async () => {
    await runLprAnalyzeInterval({
      countryHintDraft: latestCountryHintDraftRef.current,
    }, lprPorts);
  }, [lprPorts]);

  const handleSelectTargetTrack = useCallback((targetTrackId: string, preferredTimeMs?: number | null) => {
    runLprSelectTargetTrack({
      targetTrackId,
      playheadMs: livePlayheadMsRef.current,
      preferredTimeMs: preferredTimeMs ?? null,
    }, lprPorts);
  }, [livePlayheadMsRef, lprPorts]);

  const handleExportLprEvidence = useCallback(async () => {
    if (!activeFile || activeFile.asset.status !== 'ready' || (!lprTopCandidate && lprState.samples.length === 0)) {
      return;
    }

    const selectedPath = await promptLprEvidenceSavePath(
      defaultLprEvidenceFileName(activeFile, livePlayheadMsRef.current, lprTopCandidate?.text ?? null),
    );

    if (!selectedPath) {
      return;
    }

    await runLprExportEvidence({
      selectedPath,
      playheadMs: livePlayheadMsRef.current,
    }, lprPorts);
  }, [activeFile, livePlayheadMsRef, lprPorts, lprState.samples.length, lprTopCandidate]);

  // LPR progress events → use-case → store (stale payloads ignored).
  useLprProgressListener(lprPorts);

  return {
    lprRuntimeStatus,
    lprState,
    lprJob,
    lprBusy,
    lprSelectedTargetAnchor,
    lprSelectedTrack,
    lprAnalysisTrack,
    lprTopCandidate,
    lprAnalysisVehicleKind,
    canAnalyzeRange,
    latestCountryHintDraftRef,
    refreshLprRuntimeStatus,
    updateLprJob,
    handleCancelLprJob,
    applyCountryHints,
    resolveSuggestedInterval,
    handleSetIntervalBoundary,
    handleUseClipInterval,
    handleScanLprTargets,
    handleAnalyzeLprFrame,
    handleAnalyzeLprInterval,
    handleSelectTargetTrack,
    handleExportLprEvidence,
  };
}
