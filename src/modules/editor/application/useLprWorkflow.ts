import { useCallback, useEffect, useMemo, useRef } from 'react';
import { listen } from '@tauri-apps/api/event';
import { save } from '@tauri-apps/plugin-dialog';
import type { EditorWorkspaceState, EditorFileState } from '../domain/model';
import { useEditorStore } from './store/store';
import { getLprSessionByFileId } from '../domain/analysisState';
import { buildLprTargetAnchor, resolveLprAnalysisTargetVehicleKind } from '../domain/lprState';
import {
  analyzeLprFrame,
  analyzeLprInterval,
  cancelLprRuntimeJob,
  exportLprEvidence,
  getLprRuntimeStatus,
  scanLprTargets,
} from '../infrastructure/lprApi';
import { createLogger, getErrorMessage, getErrorSummary, serializeError } from '../../../utils/logger';
import { buildLprJobUpdateFromProgress, shouldApplyLprProgress } from './lprProgress';
import { INTERACTIVE_RANGE_LATENCY_BUDGET_MS, resolveLprRangeAnalysisIntent } from './lprAnalysisIntent';
import { resolveLprDisplayCandidate } from './plateWindow';
import type {
  LprProgress,
  LprSessionState,
  LprTargetTrack,
  TimelineIntervalSelection,
} from '../domain/model';
import { EDITOR_ENV } from '../config/editorEnv';
import {
  buildLprCompletionDetail,
  buildTargetTracksFromDetections,
  isAnchorWithinInterval,
  normalizeLprInterval,
  resolveStageStartedAt,
} from '../domain/lprWorkflowHelpers';
import { defaultLprEvidenceFileName } from '../domain/mediaNamingHelpers';
import { clipDurationMs, createId, createRunFolderId, findClipAtPlayhead, findClosestTrackFrame } from '../domain/model';

const log = createLogger('useLprWorkflow');

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
  currentIsPlaying,
  setWorkspaceFeedback,
}: UseLprWorkflowOptions) {
  const activeLprRequestIdRef = useRef<string | null>(null);
  const cancelledLprRequestIdsRef = useRef(new Set<string>());
  const latestCountryHintDraftRef = useRef<string | null>(null);

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
    try {
      const runtimeStatus = await getLprRuntimeStatus();
      useEditorStore.getState().setLprRuntimeStatus(runtimeStatus);
    } catch (error) {
      useEditorStore.getState().setLprRuntimeStatus({
        available: false,
        pythonExecutable: null,
        runtimeScript: null,
        version: null,
        missingPackages: [],
        installedPackages: [],
        detail: getErrorMessage(error, 'Unable to inspect the local LPR runtime.'),
      });
    }
  }, []);

  const updateLprJob = useCallback((job: Partial<LprSessionState['job']>) => {
    const timestamp = new Date().toISOString();
    useEditorStore.getState().setLprJob({
      ...job,
      stageStartedAt: resolveStageStartedAt(lprState.job, job, timestamp),
      updatedAt: timestamp,
    });
  }, [lprState.job]);

  const beginLprRequest = useCallback((stage: string, detail: string, progress: number) => {
    const requestId = createRunFolderId();
    activeLprRequestIdRef.current = requestId;
    cancelledLprRequestIdsRef.current.delete(requestId);
    updateLprJob({
      status: 'running',
      requestId,
      progress,
      stage,
      detail,
      error: null,
      reasonCode: null,
      startedAt: new Date().toISOString(),
      trackingTier: null,
      coverageRatio: null,
    });
    return requestId;
  }, [updateLprJob]);

  const forgetLprRequest = useCallback((requestId: string) => {
    if (activeLprRequestIdRef.current === requestId) {
      activeLprRequestIdRef.current = null;
    }
    cancelledLprRequestIdsRef.current.delete(requestId);
  }, []);

  const shouldIgnoreLprRequestResult = useCallback((requestId: string) => (
    activeLprRequestIdRef.current !== requestId || cancelledLprRequestIdsRef.current.has(requestId)
  ), []);

  const handleCancelLprJob = useCallback(async () => {
    const requestId = activeLprRequestIdRef.current;
    if (!requestId) {
      return;
    }

    cancelledLprRequestIdsRef.current.add(requestId);
    updateLprJob({
      status: 'cancelled',
      stage: lprJob.stage || 'LPR',
      detail: 'Cancelling current LPR task.',
      error: null,
      reasonCode: null,
    });

    try {
      await cancelLprRuntimeJob();
      if (activeLprRequestIdRef.current === requestId) {
        activeLprRequestIdRef.current = null;
      }
      updateLprJob({
        status: 'cancelled',
        progress: 1,
        stage: lprJob.stage || 'LPR',
        detail: 'Current LPR task cancelled.',
        error: null,
        reasonCode: null,
      });
      await refreshLprRuntimeStatus();
    } catch (error) {
      cancelledLprRequestIdsRef.current.delete(requestId);
      const summary = getErrorSummary(error, 'Unable to cancel the current LPR task.');
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: lprJob.stage || 'LPR',
        detail: 'Unable to cancel the current LPR task.',
        error: summary,
        reasonCode: 'cancel-failed',
      });
      setWorkspaceFeedback(summary);
    }
  }, [lprJob.stage, refreshLprRuntimeStatus, setWorkspaceFeedback, updateLprJob]);

  const applyCountryHints = useCallback((draftValue: string) => {
    const countryHints = draftValue
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    useEditorStore.getState().setLprCountryHints(countryHints);
    return countryHints;
  }, []);

  const resolveSuggestedInterval = useCallback((playheadMs: number) => {
    const activeClips = activeFile?.clips ?? [];
    const selectedClip = activeFile?.selectedClipIds[0]
      ? activeClips.find(c => c.id === activeFile.selectedClipIds[0])
      : null;
    const currentClip = selectedClip ?? findClipAtPlayhead(activeClips, playheadMs);
    if (lprState.interval) {
      return normalizeLprInterval(lprState.interval);
    }

    if (currentClip) {
      return normalizeLprInterval({
        startMs: currentClip.startMs,
        endMs: currentClip.startMs + clipDurationMs(currentClip),
      } satisfies TimelineIntervalSelection);
    }

    return normalizeLprInterval({
      startMs: Math.max(0, playheadMs - 1000),
      endMs: playheadMs + 1000,
    } satisfies TimelineIntervalSelection);
  }, [activeFile, lprState.interval]);

  const handleSetIntervalBoundary = useCallback((boundary: 'start' | 'end') => {
    const currentInterval = resolveSuggestedInterval(livePlayheadMsRef.current);
    useEditorStore.getState().setLprInterval(normalizeLprInterval({
      startMs: boundary === 'start' ? livePlayheadMsRef.current : currentInterval.startMs,
      endMs: boundary === 'end' ? livePlayheadMsRef.current : currentInterval.endMs,
    }));
  }, [livePlayheadMsRef, resolveSuggestedInterval]);

  const handleUseClipInterval = useCallback(() => {
    const activeClips = activeFile?.clips ?? [];
    const selectedClip = activeFile?.selectedClipIds[0]
      ? activeClips.find(c => c.id === activeFile.selectedClipIds[0])
      : null;
    const currentClip = selectedClip ?? findClipAtPlayhead(activeClips, livePlayheadMsRef.current);
    if (!currentClip) {
      return;
    }

    useEditorStore.getState().setLprInterval(normalizeLprInterval({
      startMs: currentClip.startMs,
      endMs: currentClip.startMs + clipDurationMs(currentClip),
    }));
  }, [activeFile, livePlayheadMsRef]);

  const handleScanLprTargets = useCallback(async () => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    const requestId = beginLprRequest('Targets', 'Scanning current frame for trackable targets.', 0.18);

    try {
      const response = await scanLprTargets({
        sourcePath: activeFile.asset.path,
        timeMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
        markerRect: activeFile.markerRect,
        targetVehicleKind: lprState.targetVehicleKind,
        requestId,
      });

      if (shouldIgnoreLprRequestResult(requestId)) {
        return;
      }

      const store = useEditorStore.getState();
      store.setLprRuntimeStatus(response.runtime);
      store.setLprTargetTracks(buildTargetTracksFromDetections(response.detections));
      store.setLprAnalysisTrack(null);
      store.setLprMode(response.detections.length > 0 ? 'target' : 'range');
      updateLprJob({
        status: 'completed',
        progress: 1,
        stage: 'Targets',
        detail: response.detections.length > 0
          ? `${response.detections.length} target(s) ready.`
          : 'No target found in the current frame.',
      });
    } catch (error) {
      if (shouldIgnoreLprRequestResult(requestId)) {
        return;
      }
      log.error('Target scan failed.', serializeError(error));
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Targets',
        detail: 'Target scan failed.',
        error: getErrorSummary(error, 'Unable to scan targets.'),
      });
      setWorkspaceFeedback(getErrorSummary(error, 'Unable to scan targets.'));
    } finally {
      forgetLprRequest(requestId);
    }
  }, [activeFile, beginLprRequest, forgetLprRequest, livePlayheadMsRef, lprState.targetVehicleKind, setWorkspaceFeedback, shouldIgnoreLprRequestResult, updateLprJob]);

  const handleAnalyzeLprFrame = useCallback(async () => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    const countryHints = applyCountryHints(
      latestCountryHintDraftRef.current ?? (lprState.countryHints.join(', ')),
    );
    const requestId = beginLprRequest('Frame', 'Analyzing the current frame.', 0.24);

    try {
      const response = await analyzeLprFrame({
        sourcePath: activeFile.asset.path,
        timeMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
        markerRect: activeFile.markerRect,
        targetVehicleKind: lprAnalysisVehicleKind,
        selectedTargetBox: lprSelectedTrack
          ? findClosestTrackFrame(lprSelectedTrack, livePlayheadMsRef.current, EDITOR_ENV.lprTargetOverlayToleranceMs)?.box ?? null
          : null,
        countryHints,
        analysisProfileId: lprState.selectedAnalysisProfileId,
        enableDeveloperDiagnostics: lprState.showDeveloperDiagnostics,
        requestId,
      });

      if (shouldIgnoreLprRequestResult(requestId)) {
        return;
      }

      const store = useEditorStore.getState();
      store.setLprRuntimeStatus(response.runtime);
      store.setLprAnalysisTrack(null);
      store.setLprSamples(response.sample ? [response.sample] : []);
      store.setLprCandidates(response.candidates);
      store.setLprReview(response.review ?? null);
      store.setLprProvenance(response.provenance ?? null);
      store.setLprDecision(response.decision ?? null);
      if (response.candidates.length > 0) {
        const completionDetail = buildLprCompletionDetail(response.candidates, response.review);
        store.appendLprHistory({
          id: createId('lpr-history'),
          createdAt: new Date().toISOString(),
          interval: null,
          targetTrackId: response.detections[0]?.id ?? null,
          acceptedCandidateId: response.acceptedCandidateId ?? null,
          analysisProfileId: lprState.selectedAnalysisProfileId,
          developerDiagnosticsEnabled: lprState.showDeveloperDiagnostics,
          candidates: response.candidates,
          summary: completionDetail,
        });
      }
      updateLprJob({
        status: response.jobStatus ?? 'completed',
        progress: 1,
        stage: 'Frame',
        detail: buildLprCompletionDetail(response.candidates, response.review),
        reasonCode: null,
        trackingTier: null,
        coverageRatio: null,
      });
    } catch (error) {
      if (shouldIgnoreLprRequestResult(requestId)) {
        return;
      }
      log.error('Frame analysis failed.', serializeError(error));
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Frame',
        detail: 'Frame analysis failed.',
        error: getErrorSummary(error, 'Unable to analyze the current frame.'),
        reasonCode: 'frame-analysis-failed',
      });
      setWorkspaceFeedback(getErrorSummary(error, 'Unable to analyze the current frame.'));
    } finally {
      forgetLprRequest(requestId);
    }
  }, [activeFile, applyCountryHints, beginLprRequest, forgetLprRequest, livePlayheadMsRef, lprAnalysisVehicleKind, lprSelectedTrack, lprState.countryHints, lprState.selectedAnalysisProfileId, lprState.showDeveloperDiagnostics, setWorkspaceFeedback, shouldIgnoreLprRequestResult, updateLprJob]);

  const handleAnalyzeLprInterval = useCallback(async () => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    if (!lprState.interval) {
      const errorMessage = 'Set Clip, In, or Out before running Range.';
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Interval',
        detail: 'Range analysis requires an explicit interval.',
        error: errorMessage,
      });
      setWorkspaceFeedback(errorMessage);
      return;
    }

    if (!lprSelectedTrack) {
      const errorMessage = 'Select a target before running Range.';
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Interval',
        detail: 'Range analysis requires a current target selection.',
        error: errorMessage,
      });
      setWorkspaceFeedback(errorMessage);
      return;
    }

    const interval = normalizeLprInterval(lprState.interval);
    if (!lprSelectedTargetAnchor) {
      const errorMessage = 'Select a target on the intended frame before running Range.';
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Interval',
        detail: 'Range analysis requires an anchored target selection.',
        error: errorMessage,
      });
      setWorkspaceFeedback(errorMessage);
      return;
    }

    if (!isAnchorWithinInterval(lprSelectedTargetAnchor.timeMs, interval)) {
      const errorMessage = 'The selected target frame is outside the current Range. Reselect the target on a frame inside the interval, or adjust In/Out.';
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Interval',
        detail: 'Range analysis requires the selected target anchor to stay inside the chosen interval.',
        error: errorMessage,
      });
      setWorkspaceFeedback(errorMessage);
      return;
    }

    const countryHints = applyCountryHints(
      latestCountryHintDraftRef.current ?? (lprState.countryHints.join(', ')),
    );
    const durationMs = Math.max(0, interval.endMs - interval.startMs);
    const analysisIntent = resolveLprRangeAnalysisIntent(durationMs, lprState.useDenseSampling);

    const requestId = beginLprRequest('Interval', 'Tracking the selected target across the chosen interval.', 0.12);

    try {
      const response = await analyzeLprInterval({
        sourcePath: activeFile.asset.path,
        interval,
        anchorTimeMs: Math.max(0, Math.round(lprSelectedTargetAnchor.timeMs)),
        targetVehicleKind: lprAnalysisVehicleKind,
        selectedTargetBox: lprSelectedTargetAnchor.box,
        selectedTargetTrackId: lprSelectedTrack?.id ?? lprState.selectedTargetTrackId ?? null,
        countryHints,
        analysisIntent,
        latencyBudgetMs: INTERACTIVE_RANGE_LATENCY_BUDGET_MS,
        analysisProfileId: lprState.selectedAnalysisProfileId,
        enableDeveloperDiagnostics: lprState.showDeveloperDiagnostics,
        requestId,
      });

      if (shouldIgnoreLprRequestResult(requestId)) {
        return;
      }

      const store = useEditorStore.getState();
      store.setLprRuntimeStatus(response.runtime);
      store.setLprInterval(interval);
      store.setLprAnalysisTrack(response.analysisTrack ?? response.targetTracks[0] ?? null);
      store.setLprSamples(response.samples);
      store.setLprCandidates(response.candidates);
      store.setLprReview(response.review ?? null);
      store.setLprProvenance(response.provenance ?? null);
      store.setLprDecision(response.decision ?? null);
      const intervalDetail = response.jobStatus === 'degraded'
        ? response.summary
        : (buildLprCompletionDetail(response.candidates, response.review) ?? response.summary);
      store.appendLprHistory({
        id: createId('lpr-history'),
        createdAt: new Date().toISOString(),
        interval,
        targetTrackId: response.analysisTrack?.id ?? lprSelectedTrack?.id ?? null,
        acceptedCandidateId: response.acceptedCandidateId ?? null,
        analysisProfileId: lprState.selectedAnalysisProfileId,
        developerDiagnosticsEnabled: lprState.showDeveloperDiagnostics,
        candidates: response.candidates,
        summary: intervalDetail,
      });
      store.setLprMode(response.candidates.length > 0 ? 'review' : 'target');
      updateLprJob({
        status: response.jobStatus ?? 'completed',
        progress: 1,
        stage: 'Interval',
        detail: intervalDetail,
        reasonCode: response.tracking?.degradedReason ?? null,
        trackingTier: response.tracking?.trackingTier ?? null,
        coverageRatio: response.tracking?.coverageRatio ?? null,
      });
    } catch (error) {
      if (shouldIgnoreLprRequestResult(requestId)) {
        return;
      }
      log.error('Range analysis failed.', serializeError(error));
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Interval',
        detail: 'Interval analysis failed.',
        error: getErrorSummary(error, 'Unable to analyze the selected interval.'),
        reasonCode: 'interval-analysis-failed',
      });
      setWorkspaceFeedback(getErrorSummary(error, 'Unable to analyze the selected interval.'));
    } finally {
      forgetLprRequest(requestId);
    }
  }, [activeFile, applyCountryHints, beginLprRequest, forgetLprRequest, lprAnalysisVehicleKind, lprSelectedTargetAnchor, lprSelectedTrack, lprState.countryHints, lprState.interval, lprState.selectedAnalysisProfileId, lprState.selectedTargetTrackId, lprState.showDeveloperDiagnostics, lprState.useDenseSampling, setWorkspaceFeedback, shouldIgnoreLprRequestResult, updateLprJob]);

  const handleSelectTargetTrack = useCallback((targetTrackId: string, preferredTimeMs?: number | null) => {
    const targetTrack = lprState.targetTracks.find((track: LprTargetTrack) => track.id === targetTrackId) ?? null;
    const targetTimeMs = Math.max(0, Math.round(preferredTimeMs ?? livePlayheadMsRef.current));
    const anchor = buildLprTargetAnchor(targetTrack, targetTimeMs);

    const store = useEditorStore.getState();
    store.selectLprTargetTrack(targetTrackId, anchor);
    store.setPlayhead(targetTimeMs);
    if (currentIsPlaying) {
      store.setPlaying(false);
    }
  }, [currentIsPlaying, livePlayheadMsRef, lprState.targetTracks]);

  const handleExportLprEvidence = useCallback(async () => {
    if (!activeFile || activeFile.asset.status !== 'ready' || (!lprTopCandidate && lprState.samples.length === 0)) {
      return;
    }

    const selectedPath = await save({
      title: 'Export LPR evidence snapshot',
      defaultPath: defaultLprEvidenceFileName(activeFile, livePlayheadMsRef.current, lprTopCandidate?.text ?? null),
      filters: [{ name: 'JSON', extensions: ['json'] }],
    });

    if (!selectedPath) {
      return;
    }

    const outputPath = selectedPath.toLowerCase().endsWith('.json') ? selectedPath : `${selectedPath}.json`;

    try {
      const response = await exportLprEvidence({
        outputPath,
        sourcePath: activeFile.asset.path,
        timeMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
        markerRect: activeFile.markerRect,
        compressionMode: activeFile.renderProfile.compressionMode,
        interval: lprState.interval,
        targetTrack: lprAnalysisTrack ?? lprSelectedTrack,
        acceptedCandidate: lprTopCandidate,
        candidates: lprState.candidates,
        samples: lprState.samples,
        review: lprState.review,
        provenance: lprState.lastAnalysisProvenance,
      });

      setWorkspaceFeedback(`Evidence bundle exported to ${response.bundleDir} with ${response.decisionFrameCount} decision frames and ${response.exportedFileCount} files.`);
    } catch (error) {
      log.error('Failed to export LPR evidence.', serializeError(error));
      setWorkspaceFeedback(getErrorSummary(error, 'Unable to export the LPR evidence snapshot.'));
    }
  }, [activeFile, livePlayheadMsRef, lprAnalysisTrack, lprSelectedTrack, lprState.candidates, lprState.interval, lprState.lastAnalysisProvenance, lprState.review, lprState.samples, lprTopCandidate, setWorkspaceFeedback]);

  // Listen to LPR Progress Events
  useEffect(() => {
    let disposed = false;
    let progressCleanup: (() => void) | undefined;

    void listen<LprProgress>('editor/lpr-progress', (event) => {
      if (disposed) {
        return;
      }

      const activeRequestId = activeLprRequestIdRef.current;
      if (!shouldApplyLprProgress(activeRequestId, event.payload)) {
        return;
      }

      updateLprJob(buildLprJobUpdateFromProgress(activeRequestId, event.payload));
    }).then((unlisten) => {
      progressCleanup = unlisten;
    });

    return () => {
      disposed = true;
      progressCleanup?.();
    };
  }, [updateLprJob]);

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
