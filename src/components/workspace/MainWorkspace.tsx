// @ts-nocheck
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import { open, save } from '@tauri-apps/plugin-dialog';
import {
  AlertCircle,
  Archive,
  Brain,
  FileOutput,
  Film,
  ImageDown,
  Import,
  Link2,
  Pause,
  Play,
  Scissors,
  SkipBack,
  SkipForward,
  Square,
  Target,
  Trash2,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import {
  clamp,
  clampNormalizedRect,
  clipDurationMs,
  createId,
  createRunFolderId,
  DEFAULT_MARKER_RECT,
  DEFAULT_ZOOM,
  findClipAtPlayhead,
  findClosestTrackFrame,
  formatRulerLabel,
  formatTransportTime,
  getActiveFile,
  getTimelineDuration,
  MAX_ZOOM,
  MIN_CLIP_DURATION_MS,
  MIN_ZOOM,
  msToPx,
  pxToMs,
  resolveTrackFrameAtPlayhead,
  type EditorAsset,
  type EditorFileState,
  type TimelineClip,
  type VideoMarkerRect,
} from '../../modules/editor/domain/model';
import { getAiEvidenceSessionByFileId, getLprSessionByFileId } from '../../modules/editor/domain/analysisState';
import { buildDefaultLprState, buildLprTargetAnchor, resolveLprAnalysisTargetVehicleKind } from '../../modules/editor/domain/lprState';
import {
  buildEditorAsset,
  exportFrameImage,
  isSupportedMediaPath,
} from '../../modules/editor/infrastructure/mediaApi';
import { analyzeAiEvidence } from '../../modules/editor/infrastructure/aiEvidenceApi';
import {
  analyzeLprFrame,
  analyzeLprInterval,
  cancelLprRuntimeJob,
  exportLprEvidence,
  getLprRuntimeStatus,
  scanLprTargets,
} from '../../modules/editor/infrastructure/lprApi';
import { createLogger, getErrorMessage, getErrorSummary, serializeError } from '../../utils/logger';
import { openExportWindow, syncExportWindowSession } from '../../modules/export/infrastructure/exportApi';
import { preparePendingExportSession } from '../../modules/export/application/exportSession';
import { EXPORT_SESSION_REQUEST_EVENT } from '../../modules/export/application/exportWindow';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../../modules/editor/application/aiPanelWindow';
import { buildLprJobUpdateFromProgress, shouldApplyLprProgress } from '../../modules/editor/application/lprProgress';
import { INTERACTIVE_RANGE_LATENCY_BUDGET_MS, resolveLprRangeAnalysisIntent } from '../../modules/editor/application/lprAnalysisIntent';
import {
  PLATE_ACTION_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  resolveLprDisplayCandidate,
  type PlateWindowAction,
  type PlateWindowSessionSnapshot,
} from '../../modules/editor/application/plateWindow';
import { emitAiPanelWindowSession, openAiPanelWindow } from '../../modules/editor/infrastructure/aiPanelApi';
import { emitPlateWindowLiveTransport, emitPlateWindowSession, openPlateWindow } from '../../modules/editor/infrastructure/plateWindowApi';
import type {
  AiEvidenceProgress,
  AiEvidenceResponse,
  LprProgress,
  LprPlateCandidate,
  LprReviewState,
  LprSessionState,
  LprTargetTrack,
  LprTrackedRegion,
  TimelineIntervalSelection,
} from '../../shared/contracts';
import {
  getPlaybackPreviewState,
  type PlaybackPreviewState,
  type PlaybackTimelineEntry,
  usePlaybackController,
} from '../../modules/editor/application/usePlaybackController';
import {
  buildLiveTransportSnapshot,
  createLiveTransportStore,
  type LiveTransportSnapshot,
  type LiveTransportStore,
} from '../../modules/editor/application/liveTransport';
import { EDITOR_ENV } from '../../shared/config/editorEnv';
import { useEditorSessionController } from '../../vnext/editor/application/useEditorSessionController';
import styles from './MainWorkspace.module.css';
import { EditorProvider } from './EditorContext';
import { Toolbar } from './toolbar/Toolbar';
import { MediaBinPanel } from './media-bin/MediaBinPanel';
import { TransportRow } from './transport-row/TransportRow';
import { VideoPlayerPanel } from './video-player/VideoPlayerPanel';
import { Timeline } from './timeline/Timeline';

const log = createLogger('MediaEditorWorkspace');

const RULER_STEP_CANDIDATES_MS = [1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000];
const MIN_TIMELINE_PADDING_MS = 60000;
const TIMELINE_LABEL_WIDTH_PX = 120;

type StageTimedJobLike = {
  status: string;
  stage: string;
  requestId: string | null;
  startedAt: string | null;
  stageStartedAt?: string | null;
};

function isActiveJobStatus(status: string | null | undefined) {
  return status === 'queued' || status === 'running';
}

function resolveStageStartedAt<TJob extends StageTimedJobLike>(
  currentJob: TJob,
  nextJob: Partial<TJob>,
  timestamp: string,
) {
  if (nextJob.stageStartedAt !== undefined) {
    return nextJob.stageStartedAt;
  }

  const nextStatus = nextJob.status ?? currentJob.status;
  const nextStage = nextJob.stage ?? currentJob.stage;
  const nextRequestId = nextJob.requestId ?? currentJob.requestId;
  const shouldResetStageClock = (
    nextRequestId !== currentJob.requestId
    || (typeof nextJob.stage === 'string' && nextStage !== currentJob.stage)
    || (!isActiveJobStatus(currentJob.status) && isActiveJobStatus(nextStatus))
    || currentJob.stageStartedAt === null
    || currentJob.stageStartedAt === undefined
  );

  if (isActiveJobStatus(nextStatus)) {
    return shouldResetStageClock ? timestamp : (currentJob.stageStartedAt ?? currentJob.startedAt ?? timestamp);
  }

  return currentJob.stageStartedAt ?? null;
}

type MarkerInteraction = {
  type: 'move' | 'resize';
  pointerId: number;
  startClientX: number;
  startClientY: number;
  originRect: VideoMarkerRect;
};

interface PreviewViewport {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface MediaEditorWorkspaceProps {
  isActive?: boolean;
}

function fitContainedViewport(containerWidth: number, containerHeight: number, sourceWidth: number, sourceHeight: number): PreviewViewport {
  if (containerWidth <= 0 || containerHeight <= 0 || sourceWidth <= 0 || sourceHeight <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }

  const scale = Math.min(containerWidth / sourceWidth, containerHeight / sourceHeight);
  const width = sourceWidth * scale;
  const height = sourceHeight * scale;

  return {
    left: (containerWidth - width) / 2,
    top: (containerHeight - height) / 2,
    width,
    height,
  };
}

function replaceExtension(fileName: string, extension: string) {
  const dotIndex = fileName.lastIndexOf('.');
  if (dotIndex === -1) {
    return `${fileName}.${extension}`;
  }

  return `${fileName.slice(0, dotIndex)}.${extension}`;
}

function frameExportExtension(_fileState: EditorFileState) {
  return 'png';
}

function defaultFrameFileName(fileState: EditorFileState, playheadMs: number) {
  const extension = frameExportExtension(fileState);
  const baseName = replaceExtension(fileState.asset.name, extension);
  const timeLabel = formatTransportTime(playheadMs).replace(/[:.]/g, '-');
  return replaceExtension(baseName, `${timeLabel}.${extension}`);
}

function defaultLprEvidenceFileName(fileState: EditorFileState, playheadMs: number, candidateText: string | null) {
  const baseName = replaceExtension(fileState.asset.name, 'json');
  const timeLabel = formatTransportTime(playheadMs).replace(/[:.]/g, '-');
  const candidateLabel = candidateText ? `_${candidateText}` : '';
  return replaceExtension(baseName, `${timeLabel}${candidateLabel}.json`);
}

function formatLprReviewReason(reason: string) {
  switch (reason) {
    case 'low-confidence':
      return 'confidence stayed low';
    case 'low-margin':
      return 'the runner-up stayed too close';
    case 'insufficient-support':
      return 'too few sampled frames agreed';
    case 'format-mismatch':
      return 'the plate pattern looked off';
    case 'no-candidate':
      return 'no readable candidate was found';
    default:
      return reason.replace(/-/g, ' ');
  }
}

function buildLprCompletionDetail(
  candidates: LprPlateCandidate[],
  review: LprReviewState | null | undefined,
) {
  const suggestedCandidate = candidates.find((candidate) => candidate.id === review?.suggestedCandidateId)
    ?? candidates[0]
    ?? null;
  if (!suggestedCandidate) {
    return 'No confident plate candidate.';
  }

  if (review?.status === 'review-required') {
    const acceptedCandidate = candidates.find((candidate) => candidate.id === review.acceptedCandidateId)
      ?? suggestedCandidate;
    const reasonLabel = review.reasons.map(formatLprReviewReason).join(', ') || 'manual review required';
    return `Best current read ${acceptedCandidate.text}. Auto-accept is paused because ${reasonLabel}.`;
  }

  const acceptedCandidate = candidates.find((candidate) => candidate.id === review?.acceptedCandidateId)
    ?? suggestedCandidate;
  return `Accepted ${acceptedCandidate.text}`;
}

function buildAiEvidenceProjectionDetail(
  candidates: LprPlateCandidate[],
  review: LprReviewState | null | undefined,
  targetTracks: LprTargetTrack[],
) {
  const completionDetail = buildLprCompletionDetail(candidates, review);
  if (completionDetail) {
    return completionDetail;
  }
  if (targetTracks.length > 0) {
    return `Resolved ${targetTracks.length} target ${targetTracks.length === 1 ? 'candidate' : 'candidates'}.`;
  }
  return 'AI evidence projection ready.';
}

function buildTargetTracksFromDetections(detections: LprTrackedRegion[]): LprTargetTrack[] {
  return detections.map((detection, index) => ({
    id: detection.id,
    className: detection.className,
    label: `${detection.className} ${index + 1}`,
    confidence: detection.confidence,
    frames: [detection],
  }));
}

function normalizeLprInterval(interval: TimelineIntervalSelection): TimelineIntervalSelection {
  const startMs = Math.max(0, Math.round(interval.startMs));
  const endMs = Math.max(0, Math.round(interval.endMs));

  return {
    startMs: Math.min(startMs, endMs),
    endMs: Math.max(startMs, endMs),
  };
}

function isAnchorWithinInterval(anchorTimeMs: number, interval: TimelineIntervalSelection) {
  return anchorTimeMs >= interval.startMs && anchorTimeMs <= interval.endMs;
}

export const MediaEditorWorkspace: React.FC<MediaEditorWorkspaceProps> = ({ isActive = true }) => {
  const { state, dispatch, sessionRevision } = useEditorSessionController();
  const [workspaceFeedback, setWorkspaceFeedback] = useState<string | null>(null);
  const [importFeedback, setImportFeedback] = useState<string | null>(null);
  const [isExternalDropActive, setIsExternalDropActive] = useState(false);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [markerInteraction, setMarkerInteraction] = useState<MarkerInteraction | null>(null);
  const [previewViewport, setPreviewViewport] = useState<PreviewViewport>({ left: 0, top: 0, width: 0, height: 0 });
  const [livePreviewState, setLivePreviewState] = useState<PlaybackPreviewState>({
    previewAsset: null,
    hasActiveVideo: false,
  });

  const previewContainerRef = useRef<HTMLDivElement>(null);
  const previewVideoRef = useRef<HTMLVideoElement>(null);
  const currentTimecodeRef = useRef<HTMLSpanElement>(null);
  const livePlayheadMsRef = useRef(0);
  const liveTransportStore = useMemo(() => createLiveTransportStore(), []);
  const plateWindowLiveSyncEnabledRef = useRef(false);
  const latestCountryHintDraftRef = useRef<string | null>(null);
  const activeLprRequestIdRef = useRef<string | null>(null);
  const cancelledLprRequestIdsRef = useRef(new Set<string>());
  const activeAiRequestRef = useRef<{ requestId: string; fileId: string } | null>(null);

  const activeFile = useMemo(() => getActiveFile(state), [state]);
  const lprRuntimeStatus = state.analysis.lprRuntimeStatus;
  const lprState = useMemo(() => getLprSessionByFileId(state.analysis, activeFile?.id ?? null), [activeFile?.id, state.analysis]);
  const aiState = useMemo(() => getAiEvidenceSessionByFileId(state.analysis, activeFile?.id ?? null), [activeFile?.id, state.analysis]);
  const currentZoom = activeFile?.zoom ?? DEFAULT_ZOOM;
  const currentPlayheadMs = activeFile?.playheadMs ?? 0;
  const currentPreviewVolume = activeFile?.previewVolume ?? 0.85;
  const currentPreviewMuted = activeFile?.previewMuted ?? false;
  const currentIsPlaying = activeFile?.isPlaying ?? false;
  const activeClips = useMemo(() => activeFile?.clips ?? [], [activeFile]);
  const selectedClipId = activeFile?.selectedClipIds[0] ?? null;
  const selectedClip = useMemo(
    () => activeClips.find((clip) => clip.id === selectedClipId) ?? null,
    [activeClips, selectedClipId],
  );
  const timelineDurationMs = useMemo(() => getTimelineDuration(activeClips), [activeClips]);
  const playbackEntries = useMemo<PlaybackTimelineEntry[]>(() => {
    if (!activeFile?.asset.url) {
      return [];
    }

    return activeClips.map((clip) => ({
      clip,
      asset: activeFile.asset,
      trackOrder: activeFile.track.order,
    }));
  }, [activeClips, activeFile]);
  const committedPreviewState = useMemo(
    () => getPlaybackPreviewState(playbackEntries, currentPlayheadMs),
    [currentPlayheadMs, playbackEntries],
  );
  const isTimelineScrubbing = isScrubbing;
  const displayPlayheadMs = currentPlayheadMs;
  const previewState = currentIsPlaying || isTimelineScrubbing ? livePreviewState : committedPreviewState;
  const missingFiles = useMemo(
    () => state.files.filter((fileState) => fileState.asset.status === 'missing'),
    [state.files],
  );
  const lprJob = lprState.job;
  const lprBusy = lprJob.status === 'queued' || lprJob.status === 'running';
  const lprSelectedTargetAnchor = lprState.selectedTargetAnchor;
  const lprSelectedTrack = useMemo(
    () => lprState.targetTracks.find((track: any) => track.id === lprState.selectedTargetTrackId) ?? null,
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
      dispatch({ type: 'set-lpr-runtime-status', runtimeStatus });
    } catch (error) {
      dispatch({
        type: 'set-lpr-runtime-status',
        runtimeStatus: {
          available: false,
          pythonExecutable: null,
          runtimeScript: null,
          version: null,
          missingPackages: [],
          installedPackages: [],
          detail: getErrorMessage(error, 'Unable to inspect the local LPR runtime.'),
        },
      });
    }
  }, [dispatch]);

  const updateLprJob = useCallback((job: Partial<LprSessionState['job']>) => {
    const timestamp = new Date().toISOString();
    dispatch({
      type: 'set-lpr-job',
      job: {
        ...job,
        stageStartedAt: resolveStageStartedAt(lprState.job, job, timestamp),
        updatedAt: timestamp,
      },
    });
  }, [dispatch, lprState.job]);

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
  }, [lprJob.stage, refreshLprRuntimeStatus, updateLprJob]);

  const applyCountryHints = useCallback((draftValue: string) => {
    const countryHints = draftValue
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    dispatch({ type: 'set-lpr-country-hints', countryHints });
    return countryHints;
  }, [dispatch]);

  const applyLiveTransportUpdate = useCallback((transport: LiveTransportSnapshot, emitPlateWindowLive = false) => {
    livePlayheadMsRef.current = transport.playheadMs;
    liveTransportStore.publish(transport);

    if (emitPlateWindowLive && plateWindowLiveSyncEnabledRef.current) {
      void emitPlateWindowLiveTransport(transport).catch(() => {
        plateWindowLiveSyncEnabledRef.current = false;
      });
    }

    if (currentTimecodeRef.current) {
      currentTimecodeRef.current.textContent = formatRulerLabel(transport.playheadMs);
    }
  }, [liveTransportStore]);

  const handleTransportUpdate = useCallback((transport: LiveTransportSnapshot) => {
    applyLiveTransportUpdate(transport, true);
  }, [applyLiveTransportUpdate]);

  const handlePreviewChange = useCallback((nextPreviewState: PlaybackPreviewState) => {
    setLivePreviewState((currentPreviewState) => {
      if (
        currentPreviewState.hasActiveVideo === nextPreviewState.hasActiveVideo
        && currentPreviewState.previewAsset?.id === nextPreviewState.previewAsset?.id
      ) {
        return currentPreviewState;
      }

      return nextPreviewState;
    });
  }, []);

  const { togglePlay, seekBy, seekTo, stopPlayback } = usePlaybackController({
    isPlaying: currentIsPlaying,
    playheadMs: currentPlayheadMs,
    timelineDurationMs,
    previewVolume: currentPreviewVolume,
    previewMuted: currentPreviewMuted,
    playbackEntries,
    videoRef: previewVideoRef,
    dispatch,
    onTransportUpdate: handleTransportUpdate,
    onPreviewChange: handlePreviewChange,
  });

  const refreshPreviewViewport = useCallback(() => {
    const container = previewContainerRef.current;
    if (!container) {
      return;
    }

    const sourceWidth = previewVideoRef.current?.videoWidth || activeFile?.asset.width || 1920;
    const sourceHeight = previewVideoRef.current?.videoHeight || activeFile?.asset.height || 1080;
    setPreviewViewport(
      fitContainedViewport(
        container.clientWidth,
        container.clientHeight,
        sourceWidth,
        sourceHeight,
      ),
    );
  }, [activeFile?.asset.height, activeFile?.asset.width]);

  useEffect(() => {
    void refreshLprRuntimeStatus();
  }, []);

  useEffect(() => {
    if (currentIsPlaying || isTimelineScrubbing) {
      return;
    }
    applyLiveTransportUpdate(
      buildLiveTransportSnapshot(currentPlayheadMs, 'paused'),
      false,
    );
  }, [activeFile?.id, applyLiveTransportUpdate, currentIsPlaying, currentPlayheadMs, isTimelineScrubbing]);

  useEffect(() => {
    if (!isActive && currentIsPlaying) {
      stopPlayback();
    }
  }, [currentIsPlaying, isActive, stopPlayback]);

  useEffect(() => {
    refreshPreviewViewport();
  }, [activeFile?.id, previewState.previewAsset?.id, refreshPreviewViewport]);

  useEffect(() => {
    const container = previewContainerRef.current;
    const video = previewVideoRef.current;
    if (!container) {
      return undefined;
    }

    const observer = new ResizeObserver(refreshPreviewViewport);
    observer.observe(container);
    video?.addEventListener('loadedmetadata', refreshPreviewViewport);

    return () => {
      observer.disconnect();
      video?.removeEventListener('loadedmetadata', refreshPreviewViewport);
    };
  }, [refreshPreviewViewport]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName;
      if (tagName === 'INPUT' || tagName === 'TEXTAREA') {
        return;
      }

      if (event.code === 'Space') {
        event.preventDefault();
        togglePlay();
      }

      if (event.key === 'Delete' || event.key === 'Backspace') {
        dispatch({ type: 'delete-selected-clips' });
      }

      if (event.key.toLowerCase() === 's' && selectedClip) {
        dispatch({ type: 'split-clip', clipId: selectedClip.id, atMs: livePlayheadMsRef.current });
      }

      if (event.key.toLowerCase() === 'm' && selectedClip) {
        dispatch({ type: 'set-selected-clips-muted', muted: !selectedClip.muted });
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedClip, togglePlay]);

  useEffect(() => {
    if (!markerInteraction || previewViewport.width <= 0 || previewViewport.height <= 0) {
      return undefined;
    }

    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerId !== markerInteraction.pointerId) {
        return;
      }

      const deltaX = (event.clientX - markerInteraction.startClientX) / previewViewport.width;
      const deltaY = (event.clientY - markerInteraction.startClientY) / previewViewport.height;
      const originRect = markerInteraction.originRect;

      if (markerInteraction.type === 'move') {
        dispatch({
          type: 'set-marker-rect',
          markerRect: {
            ...originRect,
            x: clamp(originRect.x + deltaX, 0, 1 - originRect.width),
            y: clamp(originRect.y + deltaY, 0, 1 - originRect.height),
          },
        });
        return;
      }

      dispatch({
        type: 'set-marker-rect',
        markerRect: {
          ...originRect,
          width: clamp(originRect.width + deltaX, 0.05, 1 - originRect.x),
          height: clamp(originRect.height + deltaY, 0.05, 1 - originRect.y),
        },
      });
    };

    const handlePointerUp = (event: PointerEvent) => {
      if (event.pointerId !== markerInteraction.pointerId) {
        return;
      }

      setMarkerInteraction(null);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [dispatch, markerInteraction, previewViewport.height, previewViewport.width]);

  const importMediaPaths = useCallback(async (paths: string[]) => {
    const filtered = [...new Set(paths)].filter(isSupportedMediaPath);
    if (filtered.length === 0) {
      setImportFeedback('No supported video files were selected.');
      return;
    }

    setImportFeedback(null);

    try {
      const results = await Promise.allSettled(filtered.map((path) => buildEditorAsset(path)));
      const assets = results
        .filter((result): result is PromiseFulfilledResult<EditorAsset> => result.status === 'fulfilled')
        .map((result) => result.value);
      const failures = results.filter((result) => result.status === 'rejected');

      if (assets.length > 0) {
        dispatch({ type: 'add-files', assets });
      }

      if (failures.length > 0) {
        log.warn('Some selected files failed to import.', {
          failureCount: failures.length,
          firstFailure: serializeError(failures[0].reason),
        });
        setImportFeedback(
          getErrorSummary(
            failures[0].reason,
            `${failures.length} file(s) failed to import.`,
          ),
        );
      }
    } catch (error) {
      log.error('Media import failed.', serializeError(error));
      setImportFeedback(getErrorSummary(error, 'Failed to import media.'));
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;

    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (event.payload.type === 'enter' || event.payload.type === 'over') {
          setIsExternalDropActive(true);
          return;
        }

        if (event.payload.type === 'leave') {
          setIsExternalDropActive(false);
          return;
        }

        setIsExternalDropActive(false);
        void importMediaPaths(event.payload.paths);
      })
      .then((cleanup) => {
        if (disposed) {
          cleanup();
          return;
        }

        unlisten = cleanup;
      })
      .catch(() => {
        /* dialog import remains available if drag-drop registration fails */
      });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [importMediaPaths]);

  const handleImportClick = async () => {
    const selection = await open({
      multiple: true,
      title: 'Import video files',
      filters: [
        {
          name: 'Video',
          extensions: ['mp4', 'mkv', 'mov', 'webm', 'avi', 'm4v'],
        },
      ],
    });

    if (!selection) {
      return;
    }

    await importMediaPaths(Array.isArray(selection) ? selection : [selection]);
  };



  const handleSelectFile = (fileId: string) => {
    stopPlayback();
    dispatch({ type: 'set-active-file', fileId });
  };

  const handleRemoveFile = (fileId: string) => {
    stopPlayback();
    dispatch({ type: 'remove-file', fileId });
  };

  const handleOpenExportWindow = async () => {
    stopPlayback();
    setWorkspaceFeedback(null);

    try {
      const snapshot = preparePendingExportSession(state);
      await openExportWindow(snapshot, sessionRevision);
    } catch (error) {
      log.error('Failed to open export window.', {
        error: serializeError(error),
        fileCount: state.files.length,
      });
      setWorkspaceFeedback(getErrorSummary(error, 'Failed to open export window.'));
    }
  };

  const handleToggleCompactExports = useCallback(() => {
    if (!activeFile) {
      return;
    }

    const compressionMode = activeFile.renderProfile.compressionMode === 'compact' ? 'standard' : 'compact';
    dispatch({ type: 'set-render-profile', renderProfile: { compressionMode } });

    try {
      const snapshot = preparePendingExportSession(state);
      snapshot.renderProfile = {
        ...snapshot.renderProfile,
        compressionMode,
      };
      void syncExportWindowSession(snapshot, sessionRevision);
    } catch {
      // Ignore export-session sync failures when no exportable timeline is available.
    }
  }, [activeFile, dispatch, sessionRevision, state]);

  const handleExportCurrentFrame = async () => {
    const fileState = activeFile;
    if (!fileState || fileState.asset.status !== 'ready') {
      setWorkspaceFeedback('Select a ready video file before exporting a frame.');
      return;
    }

    stopPlayback();
    const playheadMs = livePlayheadMsRef.current;
    const clip = findClipAtPlayhead(fileState.clips, playheadMs);
    if (!clip) {
      setWorkspaceFeedback('Move the playhead onto a visible clip before exporting a frame.');
      return;
    }

    const extension = frameExportExtension(fileState);
    const filterName = extension === 'jpg' ? 'JPEG Image' : 'PNG Image';
    const selectedPath = await save({
      title: 'Export current frame',
      defaultPath: defaultFrameFileName(fileState, playheadMs),
      filters: [{ name: filterName, extensions: [extension] }],
    });

    if (!selectedPath) {
      return;
    }

    const outputPath = selectedPath.toLowerCase().endsWith(`.${extension}`) ? selectedPath : `${selectedPath}.${extension}`;
    const previewTimeMs = previewVideoRef.current;
    const exportTimeMs = previewTimeMs && Number.isFinite(previewTimeMs.currentTime)
      ? previewTimeMs.currentTime * 1000
      : clip.inPointMs + (playheadMs - clip.startMs);

    try {
      await exportFrameImage({
        outputPath,
        sourcePath: fileState.asset.path,
        timeMs: exportTimeMs,
        markerRect: fileState.markerRect,
        compressionMode: fileState.renderProfile.compressionMode,
      });
      setWorkspaceFeedback(`Frame exported to ${outputPath}`);
    } catch (error) {
      log.error('Failed to export the current frame.', serializeError(error));
      setWorkspaceFeedback(getErrorSummary(error, 'Failed to export the current frame.'));
    }
  };

  const handleRelinkFile = async (fileId: string) => {
    const selection = await open({
      multiple: false,
      title: 'Relink video file',
      filters: [
        {
          name: 'Video',
          extensions: ['mp4', 'mkv', 'mov', 'webm', 'avi', 'm4v'],
        },
      ],
    });

    if (!selection || Array.isArray(selection)) {
      return;
    }

    try {
      const asset = await buildEditorAsset(selection);
      dispatch({ type: 'relink-file', fileId, asset });
      setImportFeedback(null);
    } catch (error) {
      log.error('Failed to relink media file.', serializeError(error));
      setImportFeedback(getErrorSummary(error, 'Failed to relink video.'));
    }
  };

  const handleClipPointerDown = (event: React.PointerEvent<HTMLDivElement>, clip: TimelineClip) => {
    event.stopPropagation();
    stopPlayback();
    dispatch({ type: 'set-selection', clipIds: [clip.id] });
    setInteraction({
      type: 'move',
      clipId: clip.id,
      startClientX: event.clientX,
      previewStartMs: clip.startMs,
      originStartMs: clip.startMs,
    });
  };

  const handleTrimStartPointerDown = (event: React.PointerEvent<HTMLButtonElement>, clip: TimelineClip) => {
    event.stopPropagation();
    stopPlayback();
    dispatch({ type: 'set-selection', clipIds: [clip.id] });
    setInteraction({
      type: 'trim-start',
      clipId: clip.id,
      startClientX: event.clientX,
      previewInPointMs: clip.inPointMs,
      originInPointMs: clip.inPointMs,
    });
  };

  const handleTrimEndPointerDown = (event: React.PointerEvent<HTMLButtonElement>, clip: TimelineClip) => {
    event.stopPropagation();
    stopPlayback();
    dispatch({ type: 'set-selection', clipIds: [clip.id] });
    setInteraction({
      type: 'trim-end',
      clipId: clip.id,
      startClientX: event.clientX,
      previewOutPointMs: clip.outPointMs,
      originOutPointMs: clip.outPointMs,
    });
  };

  const handleCreateMarker = () => {
    dispatch({
      type: 'set-marker-rect',
      markerRect: activeFile?.markerRect ?? DEFAULT_MARKER_RECT,
    });
  };

  const resolveSuggestedInterval = useCallback((playheadMs: number) => {
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
  }, [activeClips, lprState.interval, selectedClip]);

  const buildPlateWindowSnapshot = useCallback((): PlateWindowSessionSnapshot => ({
    workspaceName: state.workspaceName,
    activeFileName: activeFile?.asset.name ?? null,
    hasActiveFile: Boolean(activeFile),
    runtimeStatus: lprRuntimeStatus,
    lpr: lprState,
    explicitInterval: lprState.interval,
    effectiveInterval: lprState.interval,
    canAnalyzeRange,
    topCandidate: lprTopCandidate,
    anchorTimeMs: Math.max(0, Math.round(lprSelectedTargetAnchor?.timeMs ?? currentPlayheadMs)),
    playheadMs: Math.max(0, Math.round(currentPlayheadMs)),
  }), [activeFile, canAnalyzeRange, currentPlayheadMs, lprRuntimeStatus, lprSelectedTargetAnchor, lprState, lprTopCandidate, state.workspaceName]);

  const buildAiPanelWindowSnapshot = useCallback((): AiPanelSessionSnapshot => ({
    workspaceName: state.workspaceName,
    activeFileName: activeFile?.asset.name ?? null,
    hasActiveFile: Boolean(activeFile),
    runtimeStatus: lprRuntimeStatus,
    lpr: lprState,
    ai: aiState,
    playheadMs: Math.max(0, Math.round(currentPlayheadMs)),
  }), [activeFile, aiState, currentPlayheadMs, lprRuntimeStatus, lprState, state.workspaceName]);

  const updateAiJob = useCallback((fileId: string, job: Partial<typeof aiState.job>) => {
    const timestamp = new Date().toISOString();
    const currentJob = getAiEvidenceSessionByFileId(state.analysis, fileId).job;
    dispatch({
      type: 'set-ai-job',
      fileId,
      job: {
        ...job,
        stageStartedAt: resolveStageStartedAt(currentJob, job, timestamp),
        updatedAt: timestamp,
      },
    });
  }, [dispatch, state.analysis]);

  const beginAiRequest = useCallback((fileId: string, prompt: string) => {
    const requestId = createRunFolderId();
    activeAiRequestRef.current = { requestId, fileId };
    dispatch({ type: 'set-ai-prompt', fileId, prompt });
    dispatch({ type: 'set-ai-result', fileId, result: null });
    updateAiJob(fileId, {
      status: 'running',
      progress: 0.05,
      stage: 'Prepare',
      detail: 'Preparing AI evidence workflow.',
      requestId,
      error: null,
      startedAt: new Date().toISOString(),
      progressKind: 'host-step',
      toolName: null,
      toolLabel: null,
      stepIndex: 1,
      stepCount: 11,
      stageStepIndex: 1,
      stageStepCount: 1,
    });
    return requestId;
  }, [dispatch, updateAiJob]);

  const forgetAiRequest = useCallback((requestId: string) => {
    if (activeAiRequestRef.current?.requestId === requestId) {
      activeAiRequestRef.current = null;
    }
  }, []);

  const applyAiEvidenceProjection = useCallback((fileId: string, response: AiEvidenceResponse) => {
    const currentLprState = getLprSessionByFileId(state.analysis, fileId);
    const acceptedCandidateId = response.projection.acceptedCandidateId ?? null;
    const projectedTargetTracks = response.projection.targetTracks;
    const selectedTargetTrackId = response.projection.selectedTargetTrackId
      ?? response.targetSelection?.selectedTrackId
      ?? response.projection.analysisTrack?.id
      ?? currentLprState.selectedTargetTrackId;
    const projectedSelectedTrack = projectedTargetTracks.find((track: any) => track.id === selectedTargetTrackId) ?? null;
    const selectedTargetAnchor = projectedSelectedTrack
      ? buildLprTargetAnchor(projectedSelectedTrack, response.primaryAnchor?.timeMs ?? currentLprState.selectedTargetAnchor?.timeMs ?? null)
      : response.projection.analysisTrack
        ? buildLprTargetAnchor(response.projection.analysisTrack, response.primaryAnchor?.timeMs ?? response.projection.interval?.startMs ?? null)
        : currentLprState.selectedTargetAnchor;
    const projectionDetail = buildAiEvidenceProjectionDetail(
      response.projection.candidates,
      response.projection.review,
      projectedTargetTracks,
    );
    const projectedSession = buildDefaultLprState({
      ...currentLprState,
      workflowMode: response.projection.candidates.length > 0 ? 'review' : 'target',
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
        updatedAt: new Date().toISOString(),
      },
      history: response.projection.candidates.length > 0
        ? [...currentLprState.history, {
          id: createId('lpr-history'),
          createdAt: new Date().toISOString(),
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
    dispatch({ type: 'replace-lpr-session', fileId, session: projectedSession });
  }, [dispatch, state.analysis]);

  const handleCancelAiJob = useCallback(async () => {
    const activeRequest = activeAiRequestRef.current;
    if (!activeRequest) {
      return;
    }

    updateAiJob(activeRequest.fileId, {
      status: 'cancelled',
      stage: aiState.job.stage || 'AI evidence',
      detail: 'Cancelling current AI evidence task.',
      error: null,
    });

    try {
      await cancelLprRuntimeJob();
      activeAiRequestRef.current = null;
      updateAiJob(activeRequest.fileId, {
        status: 'cancelled',
        progress: 1,
        stage: aiState.job.stage || 'AI evidence',
        detail: 'Current AI evidence task cancelled.',
        error: null,
      });
      await refreshLprRuntimeStatus();
    } catch (error) {
      const summary = getErrorSummary(error, 'Unable to cancel the current AI evidence task.');
      updateAiJob(activeRequest.fileId, {
        status: 'failed',
        progress: 1,
        stage: aiState.job.stage || 'AI evidence',
        detail: 'Unable to cancel the current AI evidence task.',
        error: summary,
      });
      setWorkspaceFeedback(summary);
    }
  }, [aiState.job.stage, refreshLprRuntimeStatus, updateAiJob]);

  const handleRunAiEvidence = useCallback(async (prompt: string) => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      setWorkspaceFeedback('AI evidence analysis requires a natural-language description.');
      return;
    }

    const fileId = activeFile.id;
    const requestId = beginAiRequest(fileId, trimmedPrompt);
    setWorkspaceFeedback(null);

    try {
      const response = await analyzeAiEvidence({
        sourcePath: activeFile.asset.path,
        description: trimmedPrompt,
        markerRect: activeFile.markerRect,
        compressionMode: activeFile.renderProfile.compressionMode,
        audioBitrateKbps: activeFile.renderProfile.audioBitrateKbps,
        targetVehicleKind: lprAnalysisVehicleKind,
        countryHints: lprState.countryHints,
        analysisProfileId: lprState.selectedAnalysisProfileId,
        enableDeveloperDiagnostics: lprState.showDeveloperDiagnostics,
        requestId,
      });

      if (activeAiRequestRef.current?.requestId !== requestId || activeAiRequestRef.current?.fileId !== fileId) {
        return;
      }

      dispatch({ type: 'set-lpr-runtime-status', runtimeStatus: response.runtime });
      dispatch({ type: 'set-ai-result', fileId, result: response });
      updateAiJob(fileId, {
        status: 'completed',
        progress: 1,
        stage: 'Completed',
        detail: response.summary,
        error: null,
        requestId,
        progressKind: 'host-step',
        toolName: null,
        toolLabel: null,
        stepIndex: 11,
        stepCount: 11,
        stageStepIndex: 1,
        stageStepCount: 1,
      });
      applyAiEvidenceProjection(fileId, response);
    } catch (error) {
      if (activeAiRequestRef.current?.requestId !== requestId || activeAiRequestRef.current?.fileId !== fileId) {
        return;
      }
      log.error('AI evidence analysis failed.', serializeError(error));
      const summary = getErrorSummary(error, 'Unable to run the AI evidence workflow.');
      updateAiJob(fileId, {
        status: 'failed',
        progress: 1,
        stage: 'Failed',
        detail: 'AI evidence analysis failed.',
        error: summary,
        requestId,
        progressKind: 'host-step',
        toolName: null,
        toolLabel: null,
        stepIndex: 11,
        stepCount: 11,
        stageStepIndex: 1,
        stageStepCount: 1,
      });
      setWorkspaceFeedback(summary);
    } finally {
      forgetAiRequest(requestId);
    }
  }, [activeFile, applyAiEvidenceProjection, beginAiRequest, dispatch, forgetAiRequest, lprAnalysisVehicleKind, lprState.countryHints, lprState.selectedAnalysisProfileId, lprState.showDeveloperDiagnostics, updateAiJob]);

  const handleSetIntervalBoundary = (boundary: 'start' | 'end') => {
    const currentInterval = resolveSuggestedInterval(livePlayheadMsRef.current);
    dispatch({
      type: 'set-lpr-interval',
      interval: normalizeLprInterval({
        startMs: boundary === 'start' ? livePlayheadMsRef.current : currentInterval.startMs,
        endMs: boundary === 'end' ? livePlayheadMsRef.current : currentInterval.endMs,
      }),
    });
  };

  const handleUseClipInterval = () => {
    const currentClip = selectedClip ?? findClipAtPlayhead(activeClips, livePlayheadMsRef.current);
    if (!currentClip) {
      return;
    }

    dispatch({
      type: 'set-lpr-interval',
      interval: normalizeLprInterval({
        startMs: currentClip.startMs,
        endMs: currentClip.startMs + clipDurationMs(currentClip),
      }),
    });
  };

  const handleScanLprTargets = async () => {
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

      dispatch({ type: 'set-lpr-runtime-status', runtimeStatus: response.runtime });
      dispatch({ type: 'set-lpr-target-tracks', targetTracks: buildTargetTracksFromDetections(response.detections) });
      dispatch({ type: 'set-lpr-analysis-track', analysisTrack: null });
      dispatch({ type: 'set-lpr-mode', workflowMode: response.detections.length > 0 ? 'target' : 'range' });
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
  };

  const handleAnalyzeLprFrame = async () => {
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

      dispatch({ type: 'set-lpr-runtime-status', runtimeStatus: response.runtime });
      dispatch({ type: 'set-lpr-analysis-track', analysisTrack: null });
      dispatch({ type: 'set-lpr-samples', samples: response.sample ? [response.sample] : [] });
      dispatch({ type: 'set-lpr-candidates', candidates: response.candidates });
      dispatch({ type: 'set-lpr-review', review: response.review ?? null });
      dispatch({ type: 'set-lpr-provenance', provenance: response.provenance ?? null });
      dispatch({ type: 'set-lpr-decision', decision: response.decision ?? null });
      if (response.candidates.length > 0) {
        const completionDetail = buildLprCompletionDetail(response.candidates, response.review);
        dispatch({
          type: 'append-lpr-history',
          entry: {
            id: createId('lpr-history'),
            createdAt: new Date().toISOString(),
            interval: null,
            targetTrackId: response.detections[0]?.id ?? null,
            acceptedCandidateId: response.acceptedCandidateId ?? null,
            analysisProfileId: lprState.selectedAnalysisProfileId,
            developerDiagnosticsEnabled: lprState.showDeveloperDiagnostics,
            candidates: response.candidates,
            summary: completionDetail,
          },
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
  };

  const handleAnalyzeLprInterval = async () => {
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

      dispatch({ type: 'set-lpr-runtime-status', runtimeStatus: response.runtime });
      dispatch({ type: 'set-lpr-interval', interval });
      dispatch({ type: 'set-lpr-analysis-track', analysisTrack: response.analysisTrack ?? response.targetTracks[0] ?? null });
      dispatch({ type: 'set-lpr-samples', samples: response.samples });
      dispatch({ type: 'set-lpr-candidates', candidates: response.candidates });
      dispatch({ type: 'set-lpr-review', review: response.review ?? null });
      dispatch({ type: 'set-lpr-provenance', provenance: response.provenance ?? null });
      dispatch({ type: 'set-lpr-decision', decision: response.decision ?? null });
      const intervalDetail = response.jobStatus === 'degraded'
        ? response.summary
        : (buildLprCompletionDetail(response.candidates, response.review) ?? response.summary);
      dispatch({
        type: 'append-lpr-history',
        entry: {
          id: createId('lpr-history'),
          createdAt: new Date().toISOString(),
          interval,
          targetTrackId: response.analysisTrack?.id ?? lprSelectedTrack?.id ?? null,
          acceptedCandidateId: response.acceptedCandidateId ?? null,
          analysisProfileId: lprState.selectedAnalysisProfileId,
          developerDiagnosticsEnabled: lprState.showDeveloperDiagnostics,
          candidates: response.candidates,
          summary: intervalDetail,
        },
      });
      dispatch({ type: 'set-lpr-mode', workflowMode: response.candidates.length > 0 ? 'review' : 'target' });
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
  };

  const handleSelectTargetTrack = useCallback((targetTrackId: string, preferredTimeMs?: number | null) => {
    const targetTrack = lprState.targetTracks.find((track: any) => track.id === targetTrackId) ?? null;
    const targetTimeMs = Math.max(0, Math.round(preferredTimeMs ?? livePlayheadMsRef.current));
    const anchor = buildLprTargetAnchor(targetTrack, targetTimeMs);

    dispatch({ type: 'select-lpr-target-track', targetTrackId, anchor });
    dispatch({ type: 'set-playhead', playheadMs: targetTimeMs });
    if (currentIsPlaying) {
      dispatch({ type: 'set-playing', isPlaying: false });
    }
  }, [currentIsPlaying, dispatch, lprState.targetTracks]);

  const handleExportLprEvidence = async () => {
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
  };

  const handleOpenPlateWindow = async () => {
    await openPlateWindow();
    plateWindowLiveSyncEnabledRef.current = true;
    await emitPlateWindowSession(buildPlateWindowSnapshot(), sessionRevision).catch(() => undefined);
  };

  const handleOpenAiPanelWindow = async () => {
    await openAiPanelWindow();
    await emitAiPanelWindowSession(buildAiPanelWindowSnapshot(), sessionRevision).catch(() => undefined);
  };

  const handlePlateWindowAction = React.useEffectEvent(async (action: PlateWindowAction) => {
    switch (action.type) {
      case 'refresh-runtime':
        await refreshLprRuntimeStatus();
        break;
      case 'cancel-job':
        await handleCancelLprJob();
        break;
      case 'use-clip-interval':
        handleUseClipInterval();
        break;
      case 'set-interval-boundary':
        handleSetIntervalBoundary(action.boundary);
        break;
      case 'clear-interval':
        dispatch({ type: 'clear-lpr-interval' });
        break;
      case 'set-analysis-profile':
        dispatch({ type: 'set-lpr-analysis-profile', analysisProfileId: action.analysisProfileId });
        break;
      case 'set-country-hints':
        latestCountryHintDraftRef.current = action.value;
        applyCountryHints(action.value);
        break;
      case 'scan-targets':
        await handleScanLprTargets();
        break;
      case 'analyze-frame':
        await handleAnalyzeLprFrame();
        break;
      case 'analyze-range':
        await handleAnalyzeLprInterval();
        break;
      case 'toggle-dense-sampling':
        dispatch({ type: 'set-lpr-toggles', toggles: { useDenseSampling: !lprState.useDenseSampling } });
        break;
      case 'toggle-developer-diagnostics':
        dispatch({ type: 'set-lpr-toggles', toggles: { showDeveloperDiagnostics: !lprState.showDeveloperDiagnostics } });
        break;
      case 'export-evidence':
        await handleExportLprEvidence();
        break;
      case 'clear-results':
        dispatch({ type: 'clear-lpr-results' });
        break;
      case 'select-target-track':
        handleSelectTargetTrack(action.targetTrackId, action.anchorTimeMs);
        break;
      case 'accept-candidate':
        dispatch({ type: 'accept-lpr-candidate', candidateId: action.candidateId });
        break;
      case 'seek-to-sample':
        dispatch({ type: 'set-playhead', playheadMs: Math.max(0, Math.round(action.timeMs)) });
        if (currentIsPlaying) {
          dispatch({ type: 'set-playing', isPlaying: false });
        }
        break;
      default:
        break;
    }
  });

  const handlePlateWindowSessionRequest = React.useEffectEvent(async () => {
    plateWindowLiveSyncEnabledRef.current = true;
    await emitPlateWindowSession(buildPlateWindowSnapshot(), sessionRevision).catch(() => undefined);
  });

  const handleAiPanelAction = React.useEffectEvent(async (action: AiPanelAction) => {
    switch (action.type) {
      case 'run-analysis':
        await handleRunAiEvidence(action.prompt);
        break;
      case 'cancel-job':
        await handleCancelAiJob();
        break;
      case 'seek-to-time':
        dispatch({ type: 'set-playhead', playheadMs: Math.max(0, Math.round(action.timeMs)) });
        if (currentIsPlaying) {
          dispatch({ type: 'set-playing', isPlaying: false });
        }
        break;
      case 'reset-session':
        if (activeFile) {
          dispatch({ type: 'reset-ai-session', fileId: activeFile.id });
        }
        break;
      default:
        break;
    }
  });

  const handleAiPanelSessionRequest = React.useEffectEvent(async () => {
    await emitAiPanelWindowSession(buildAiPanelWindowSnapshot(), sessionRevision).catch(() => undefined);
  });

  const handleExportWindowSessionRequest = React.useEffectEvent(async () => {
    try {
      const snapshot = preparePendingExportSession(state);
      await syncExportWindowSession(snapshot, sessionRevision).catch(() => undefined);
    } catch {
      // Ignore export-session requests when no exportable timeline is available.
    }
  });

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

  useEffect(() => {
    let disposed = false;
    let progressCleanup: (() => void) | undefined;

    void listen<AiEvidenceProgress>('editor/ai-evidence-progress', (event) => {
      if (disposed) {
        return;
      }

      const activeRequest = activeAiRequestRef.current;
      if (!activeRequest) {
        return;
      }

      if (event.payload.requestId && event.payload.requestId !== activeRequest.requestId) {
        return;
      }

      updateAiJob(activeRequest.fileId, {
        status: event.payload.failed ? 'failed' : event.payload.done ? 'completed' : 'running',
        progress: Math.max(0, Math.min(1, event.payload.progress)),
        stage: event.payload.stage,
        detail: event.payload.detail,
        requestId: activeRequest.requestId,
        error: event.payload.failed ? event.payload.detail : null,
        progressKind: event.payload.progressKind ?? null,
        toolName: event.payload.toolName ?? null,
        toolLabel: event.payload.toolLabel ?? null,
        stepIndex: event.payload.stepIndex ?? null,
        stepCount: event.payload.stepCount ?? null,
        stageStepIndex: event.payload.stageStepIndex ?? null,
        stageStepCount: event.payload.stageStepCount ?? null,
      });
    }).then((unlisten) => {
      progressCleanup = unlisten;
    });

    return () => {
      disposed = true;
      progressCleanup?.();
    };
  }, [updateAiJob]);

  useEffect(() => {
    let disposed = false;
    let actionCleanup: (() => void) | undefined;
    let requestCleanup: (() => void) | undefined;

    void listen<PlateWindowAction>(PLATE_ACTION_EVENT, (event) => {
      if (disposed) {
        return;
      }

      void handlePlateWindowAction(event.payload);
    }).then((unlisten) => {
      actionCleanup = unlisten;
    });

    void listen(PLATE_SESSION_REQUEST_EVENT, () => {
      if (disposed) {
        return;
      }

      void handlePlateWindowSessionRequest();
    }).then((unlisten) => {
      requestCleanup = unlisten;
    });

    return () => {
      disposed = true;
      actionCleanup?.();
      requestCleanup?.();
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    let exportRequestCleanup: (() => void) | undefined;
    let actionCleanup: (() => void) | undefined;
    let requestCleanup: (() => void) | undefined;

    void listen<AiPanelAction>(AI_PANEL_ACTION_EVENT, (event) => {
      if (disposed) {
        return;
      }

      void handleAiPanelAction(event.payload);
    }).then((unlisten) => {
      actionCleanup = unlisten;
    });

    void listen(AI_PANEL_SESSION_REQUEST_EVENT, () => {
      if (disposed) {
        return;
      }

      void handleAiPanelSessionRequest();
    }).then((unlisten) => {
      requestCleanup = unlisten;
    });

    void listen(EXPORT_SESSION_REQUEST_EVENT, () => {
      if (disposed) {
        return;
      }

      void handleExportWindowSessionRequest();
    }).then((unlisten) => {
      exportRequestCleanup = unlisten;
    });

    return () => {
      disposed = true;
      exportRequestCleanup?.();
      actionCleanup?.();
      requestCleanup?.();
    };
  }, []);

  useEffect(() => {
    void emitPlateWindowSession(buildPlateWindowSnapshot(), sessionRevision).catch(() => undefined);
  }, [buildPlateWindowSnapshot, sessionRevision]);

  useEffect(() => {
    void emitAiPanelWindowSession(buildAiPanelWindowSnapshot(), sessionRevision).catch(() => undefined);
  }, [buildAiPanelWindowSnapshot, sessionRevision]);

  const handleMarkerPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!activeFile?.markerRect) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    setMarkerInteraction({
      type: 'move',
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originRect: activeFile.markerRect,
    });
  };

  const handleMarkerResizePointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!activeFile?.markerRect) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    setMarkerInteraction({
      type: 'resize',
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originRect: activeFile.markerRect,
    });
  };

  const markerStyle = activeFile?.markerRect ? {
    left: `${previewViewport.left + (activeFile.markerRect.x * previewViewport.width)}px`,
    top: `${previewViewport.top + (activeFile.markerRect.y * previewViewport.height)}px`,
    width: `${activeFile.markerRect.width * previewViewport.width}px`,
    height: `${activeFile.markerRect.height * previewViewport.height}px`,
  } : undefined;

  return (
    <EditorProvider value={{ state, dispatch, activeFile: activeFile ?? undefined }}>
      <div className={styles.editor}>
      <Toolbar
        activeFile={activeFile ?? null}
        onExportCurrentFrame={handleExportCurrentFrame}
        onOpenExportWindow={handleOpenExportWindow}
        onOpenPlateWindow={handleOpenPlateWindow}
        onOpenAiPanelWindow={handleOpenAiPanelWindow}
        onToggleCompactExports={handleToggleCompactExports}
        onImportClick={handleImportClick}
      />

      {(workspaceFeedback || importFeedback) && (
        <section className={styles.noticeBar}>
          {workspaceFeedback && (
            <div className={`${styles.notice} ${styles.noticeError}`}>
              <AlertCircle size={15} />
              <span>{workspaceFeedback}</span>
            </div>
          )}
          {importFeedback && (
            <div className={`${styles.notice} ${styles.noticeError}`}>
              <AlertCircle size={15} />
              <span>{importFeedback}</span>
            </div>
          )}
        </section>
      )}

      <div className={styles.content}>
        <MediaBinPanel
          isExternalDropActive={isExternalDropActive}
          missingFiles={missingFiles}
          handleImportClick={handleImportClick}
          handleSelectFile={handleSelectFile}
          handleRelinkFile={handleRelinkFile}
          handleRemoveFile={handleRemoveFile}
        />

        <main className={styles.mainPanel}>
          <VideoPlayerPanel
            previewContainerRef={previewContainerRef}
            previewVideoRef={previewVideoRef}
            previewState={previewState}
            previewViewport={previewViewport}
            lprState={lprState}
            lprAnalysisTrack={lprAnalysisTrack}
            liveTransportStore={liveTransportStore}
            handleSelectTargetTrack={handleSelectTargetTrack}
            markerStyle={markerStyle}
            handleMarkerPointerDown={handleMarkerPointerDown}
            handleMarkerResizePointerDown={handleMarkerResizePointerDown}
            handleCreateMarker={handleCreateMarker}
          />

          <TransportRow
            currentTimecodeRef={currentTimecodeRef}
            displayPlayheadMs={displayPlayheadMs}
            livePlayheadMsRef={livePlayheadMsRef}
            seekBy={seekBy}
            togglePlay={togglePlay}
          />

          <Timeline
            activeFile={activeFile ?? null}
            activeClips={activeClips}
            timelineDurationMs={timelineDurationMs}
            liveTransportStore={liveTransportStore}
            dispatch={dispatch}
            seekTo={seekTo}
            stopPlayback={stopPlayback}
            onScrubStateChange={setIsScrubbing}
          />
        </main>
      </div>

    </div>
    </EditorProvider>
  );
};
