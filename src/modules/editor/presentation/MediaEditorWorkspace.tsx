import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
} from '../domain/model';
import { getAiEvidenceSessionByFileId, getLprSessionByFileId } from '../domain/analysisState';
import { buildDefaultLprState, buildLprTargetAnchor, resolveLprAnalysisTargetVehicleKind } from '../domain/lprState';
import {
  buildEditorAsset,
  exportFrameImage,
  isSupportedMediaPath,
} from '../infrastructure/mediaApi';
import { analyzeAiEvidence } from '../infrastructure/aiEvidenceApi';
import {
  analyzeLprFrame,
  analyzeLprInterval,
  cancelLprRuntimeJob,
  exportLprEvidence,
  getLprRuntimeStatus,
  scanLprTargets,
} from '../infrastructure/lprApi';
import { createLogger, getErrorMessage, getErrorSummary, serializeError } from '../../../utils/logger';
import { openExportWindow, syncExportWindowSession } from '../../export/infrastructure/exportApi';
import { preparePendingExportSession } from '../../export/application/exportSession';
import { EXPORT_SESSION_REQUEST_EVENT } from '../../export/application/exportWindow';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';
import { buildLprJobUpdateFromProgress, shouldApplyLprProgress } from '../application/lprProgress';
import {
  PLATE_ACTION_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  type PlateWindowAction,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';
import { emitAiPanelWindowSession, openAiPanelWindow } from '../infrastructure/aiPanelApi';
import { emitPlateWindowSession, openPlateWindow } from '../infrastructure/plateWindowApi';
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
} from '../../../shared/contracts';
import {
  getPlaybackPreviewState,
  type PlaybackPreviewState,
  type PlaybackTimelineEntry,
  usePlaybackController,
} from '../application/usePlaybackController';
import { EDITOR_ENV } from '../../../shared/config/editorEnv';
import { useEditorSessionController } from '../../../vnext/editor/application/useEditorSessionController';
import styles from './MediaEditorWorkspace.module.css';

const log = createLogger('MediaEditorWorkspace');

const RULER_STEP_CANDIDATES_MS = [1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000];
const MIN_TIMELINE_PADDING_MS = 60000;
const TIMELINE_LABEL_WIDTH_PX = 120;

type ClipInteraction =
  | {
    type: 'move';
    clipId: string;
    startClientX: number;
    previewStartMs: number;
    originStartMs: number;
  }
  | {
    type: 'trim-start';
    clipId: string;
    startClientX: number;
    previewInPointMs: number;
    originInPointMs: number;
  }
  | {
    type: 'trim-end';
    clipId: string;
    startClientX: number;
    previewOutPointMs: number;
    originOutPointMs: number;
  };

type MarkerInteraction = {
  type: 'move' | 'resize';
  pointerId: number;
  startClientX: number;
  startClientY: number;
  originRect: VideoMarkerRect;
};

type TimelineScrubState = {
  pointerId: number;
  surfaceLeft: number;
  preservePlayback: boolean;
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

type LprOverlayLayerHandle = {
  setPlayheadMs: (playheadMs: number) => void;
};

type LprOverlayTargetEntry = {
  trackId: string;
  label: string;
  selectionTrackId: string | null;
  isSelected: boolean;
  frame: LprTrackedRegion;
};

type LprOverlayLayerProps = {
  previewViewport: PreviewViewport;
  targetTracks: LprTargetTrack[];
  analysisTrack: LprTargetTrack | null;
  selectedTargetTrackId: string | null;
  basePlayheadMs: number;
  onSelectTrack: (targetTrackId: string, preferredTimeMs?: number | null) => void;
};

const LprOverlayTargetButton = React.memo(function LprOverlayTargetButton({
  entry,
  previewViewport,
  onSelectTrack,
}: {
  entry: LprOverlayTargetEntry;
  previewViewport: PreviewViewport;
  onSelectTrack: (targetTrackId: string, preferredTimeMs?: number | null) => void;
}) {
  const box = clampNormalizedRect(entry.frame.box);
  const overlayStyle = {
    width: `${box.width * previewViewport.width}px`,
    height: `${box.height * previewViewport.height}px`,
    transform: `translate3d(${previewViewport.left + (box.x * previewViewport.width)}px, ${previewViewport.top + (box.y * previewViewport.height)}px, 0)`,
  } satisfies React.CSSProperties;

  return (
    <button
      type="button"
      className={`${styles.lprOverlayTarget} ${entry.isSelected ? styles.lprOverlayTargetSelected : ''}`}
      style={overlayStyle}
      onClick={() => entry.selectionTrackId && onSelectTrack(entry.selectionTrackId, entry.frame.timeMs)}
    >
      <span className={styles.lprOverlayLabel}>{entry.label}</span>
    </button>
  );
});

const LprPreviewOverlayLayer = React.memo(React.forwardRef<LprOverlayLayerHandle, LprOverlayLayerProps>(function LprPreviewOverlayLayer({
  previewViewport,
  targetTracks,
  analysisTrack,
  selectedTargetTrackId,
  basePlayheadMs,
  onSelectTrack,
}, ref) {
  const [overlayPlayheadMs, setOverlayPlayheadMs] = useState(basePlayheadMs);
  const queuedPlayheadMsRef = useRef(basePlayheadMs);
  const committedPlayheadMsRef = useRef(basePlayheadMs);
  const animationFrameRef = useRef<number | null>(null);

  const commitOverlayPlayhead = useCallback((playheadMs: number) => {
    if (Math.abs(playheadMs - committedPlayheadMsRef.current) < 1) {
      return;
    }
    committedPlayheadMsRef.current = playheadMs;
    setOverlayPlayheadMs(playheadMs);
  }, []);

  const flushQueuedPlayhead = useCallback(() => {
    animationFrameRef.current = null;
    commitOverlayPlayhead(queuedPlayheadMsRef.current);
  }, [commitOverlayPlayhead]);

  const schedulePlayhead = useCallback((playheadMs: number) => {
    queuedPlayheadMsRef.current = playheadMs;
    if (animationFrameRef.current !== null) {
      return;
    }
    animationFrameRef.current = window.requestAnimationFrame(flushQueuedPlayhead);
  }, [flushQueuedPlayhead]);

  React.useImperativeHandle(ref, () => ({
    setPlayheadMs(playheadMs: number) {
      schedulePlayhead(playheadMs);
    },
  }), [schedulePlayhead]);

  useEffect(() => {
    queuedPlayheadMsRef.current = basePlayheadMs;
    committedPlayheadMsRef.current = basePlayheadMs;
    setOverlayPlayheadMs(basePlayheadMs);
  }, [basePlayheadMs, targetTracks, analysisTrack, selectedTargetTrackId]);

  useEffect(() => () => {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
    }
  }, []);

  const overlayEntries = useMemo<LprOverlayTargetEntry[]>(() => {
    const targetLabels = new Map(targetTracks.map((track) => [track.id, track.label]));
    return [
      ...targetTracks
        .filter((track) => track.id !== analysisTrack?.id)
        .flatMap((track) => {
          const frame = findClosestTrackFrame(track, overlayPlayheadMs, EDITOR_ENV.lprTargetOverlayToleranceMs);
          if (!frame) {
            return [];
          }
          return [{
            trackId: track.id,
            label: track.label,
            selectionTrackId: track.id,
            isSelected: track.id === selectedTargetTrackId,
            frame,
          }];
        }),
      ...(analysisTrack ? (() => {
        const frame = resolveTrackFrameAtPlayhead(
          analysisTrack,
          overlayPlayheadMs,
          EDITOR_ENV.lprTargetOverlayToleranceMs,
          EDITOR_ENV.lprAnalysisInterpolationGapMs,
        );
        if (!frame) {
          return [];
        }
        return [{
          trackId: analysisTrack.id,
          label: targetLabels.get(selectedTargetTrackId ?? '') ?? analysisTrack.label,
          selectionTrackId: selectedTargetTrackId ?? analysisTrack.id,
          isSelected: (selectedTargetTrackId ?? analysisTrack.id) === selectedTargetTrackId,
          frame,
        } satisfies LprOverlayTargetEntry];
      })() : []),
    ];
  }, [analysisTrack, overlayPlayheadMs, selectedTargetTrackId, targetTracks]);

  if (previewViewport.width <= 0) {
    return null;
  }

  return (
    <>
      {overlayEntries.map((entry) => (
        <LprOverlayTargetButton
          key={entry.trackId}
          entry={entry}
          previewViewport={previewViewport}
          onSelectTrack={onSelectTrack}
        />
      ))}
    </>
  );
}));

function rulerStepForZoom(zoom: number) {
  return (
    RULER_STEP_CANDIDATES_MS.find((stepMs) => msToPx(stepMs, zoom) >= 92)
    ?? RULER_STEP_CANDIDATES_MS.at(-1)
    ?? 1000
  );
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
    const reasonLabel = review.reasons.map(formatLprReviewReason).join(', ') || 'manual review required';
    return `Best current read ${suggestedCandidate.text}. Auto-accept is paused because ${reasonLabel}.`;
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
  const [timelineViewportWidth, setTimelineViewportWidth] = useState(0);
  const [timelineScrollLeft, setTimelineScrollLeft] = useState(0);
  const [interaction, setInteraction] = useState<ClipInteraction | null>(null);
  const [timelineScrub, setTimelineScrub] = useState<TimelineScrubState | null>(null);
  const [markerInteraction, setMarkerInteraction] = useState<MarkerInteraction | null>(null);
  const [previewViewport, setPreviewViewport] = useState<PreviewViewport>({ left: 0, top: 0, width: 0, height: 0 });
  const [livePreviewState, setLivePreviewState] = useState<PlaybackPreviewState>({
    previewAsset: null,
    hasActiveVideo: false,
  });

  const zoomRef = useRef(DEFAULT_ZOOM);
  const pendingZoomAnchorRef = useRef<{ anchorMs: number; viewportX: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const timelineCanvasRef = useRef<HTMLDivElement>(null);
  const previewContainerRef = useRef<HTMLDivElement>(null);
  const previewVideoRef = useRef<HTMLVideoElement>(null);
  const currentTimecodeRef = useRef<HTMLSpanElement>(null);
  const livePlayheadMsRef = useRef(0);
  const lprOverlayLayerRef = useRef<LprOverlayLayerHandle | null>(null);
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
  const trackMuted = useMemo(
    () => activeClips.length > 0 && activeClips.every((clip) => clip.muted),
    [activeClips],
  );
  const timelineDurationMs = useMemo(() => getTimelineDuration(activeClips), [activeClips]);
  const timelineVisibleWidthPx = useMemo(
    () => Math.max(240, timelineViewportWidth - TIMELINE_LABEL_WIDTH_PX),
    [timelineViewportWidth],
  );
  const visibleDurationMs = useMemo(
    () => pxToMs(timelineVisibleWidthPx, currentZoom),
    [currentZoom, timelineVisibleWidthPx],
  );
  const timelinePaddingMs = useMemo(
    () => Math.max(MIN_TIMELINE_PADDING_MS, visibleDurationMs * 2),
    [visibleDurationMs],
  );
  const timelineRangeEndMs = useMemo(() => {
    const visibleEndMs = pxToMs(timelineScrollLeft + timelineVisibleWidthPx, currentZoom);
    return Math.max(
      visibleDurationMs,
      timelineDurationMs + timelinePaddingMs,
      currentPlayheadMs + timelinePaddingMs,
      visibleEndMs + timelinePaddingMs,
    );
  }, [currentPlayheadMs, currentZoom, timelineDurationMs, timelinePaddingMs, timelineScrollLeft, timelineVisibleWidthPx, visibleDurationMs]);
  const timelineWidthPx = useMemo(
    () => Math.max(timelineVisibleWidthPx, Math.round(msToPx(timelineRangeEndMs, currentZoom) + 120)),
    [currentZoom, timelineRangeEndMs, timelineVisibleWidthPx],
  );
  const fitZoom = useMemo(() => {
    if (timelineDurationMs <= 0 || timelineViewportWidth <= 0) {
      return currentZoom;
    }

    const usableWidth = Math.max(240, timelineVisibleWidthPx - 12);
    return clamp((usableWidth / timelineDurationMs) * 1000, MIN_ZOOM, MAX_ZOOM);
  }, [currentZoom, timelineDurationMs, timelineViewportWidth, timelineVisibleWidthPx]);
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
  const isTimelineScrubbing = timelineScrub !== null;
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
    () => lprState.targetTracks.find((track) => track.id === lprState.selectedTargetTrackId) ?? null,
    [lprState.selectedTargetTrackId, lprState.targetTracks],
  );
  const lprAnalysisTrack = lprState.analysisTrack;
  const lprAcceptedCandidate = useMemo(
    () => lprState.candidates.find((candidate) => candidate.id === lprState.acceptedCandidateId) ?? null,
    [lprState.acceptedCandidateId, lprState.candidates],
  );
  const lprTopCandidate = lprAcceptedCandidate ?? lprState.candidates[0] ?? null;
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
    dispatch({
      type: 'set-lpr-job',
      job: {
        ...job,
        updatedAt: new Date().toISOString(),
      },
    });
  }, [dispatch]);

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

  const applyLiveTransportFrame = useCallback((playheadMs: number) => {
    livePlayheadMsRef.current = playheadMs;
    lprOverlayLayerRef.current?.setPlayheadMs(playheadMs);

    if (currentTimecodeRef.current) {
      currentTimecodeRef.current.textContent = formatRulerLabel(playheadMs);
    }

    if (timelineCanvasRef.current) {
      timelineCanvasRef.current.style.setProperty('--playhead-left', `${msToPx(playheadMs, zoomRef.current)}px`);
    }
  }, []);

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
    onTransportFrame: applyLiveTransportFrame,
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
    zoomRef.current = currentZoom;
  }, [currentZoom]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void refreshLprRuntimeStatus();
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [refreshLprRuntimeStatus]);

  useEffect(() => {
    applyLiveTransportFrame(currentPlayheadMs);
  }, [applyLiveTransportFrame, currentPlayheadMs, activeFile?.id]);

  useEffect(() => {
    applyLiveTransportFrame(livePlayheadMsRef.current);
  }, [applyLiveTransportFrame, currentZoom, timelineWidthPx]);

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
    const scroller = scrollRef.current;
    if (!scroller) {
      return undefined;
    }

    let frameId = 0;
    const updateMetrics = () => {
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(() => {
        setTimelineViewportWidth(scroller.clientWidth);
        setTimelineScrollLeft(scroller.scrollLeft);
      });
    };

    updateMetrics();

    const observer = new ResizeObserver(updateMetrics);
    observer.observe(scroller);
    scroller.addEventListener('scroll', updateMetrics, { passive: true });

    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
      scroller.removeEventListener('scroll', updateMetrics);
    };
  }, []);

  const handleTimelineWheelZoom = useCallback((event: WheelEvent) => {
    if (!event.ctrlKey || !activeFile) {
      return;
    }

    const scroller = scrollRef.current;
    if (!scroller) {
      return;
    }

    event.preventDefault();

    const bounds = scroller.getBoundingClientRect();
    const cursorX = clamp(event.clientX - bounds.left - TIMELINE_LABEL_WIDTH_PX, 0, timelineVisibleWidthPx);
    const currentTimelineZoom = zoomRef.current;
    const cursorTimelineX = Math.max(0, scroller.scrollLeft + cursorX);
    const anchorMs = pxToMs(cursorTimelineX, currentTimelineZoom);
    const nextZoom = clamp(currentTimelineZoom * Math.exp(-event.deltaY * 0.0015), MIN_ZOOM, MAX_ZOOM);

    if (Math.abs(nextZoom - currentTimelineZoom) < 0.001) {
      return;
    }

    zoomRef.current = nextZoom;
    pendingZoomAnchorRef.current = { anchorMs, viewportX: cursorX };
    dispatch({ type: 'set-zoom', zoom: nextZoom });
  }, [activeFile, timelineVisibleWidthPx]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) {
      return undefined;
    }

    const onWheel = (event: WheelEvent) => handleTimelineWheelZoom(event);
    scroller.addEventListener('wheel', onWheel, { passive: false });

    return () => scroller.removeEventListener('wheel', onWheel);
  }, [handleTimelineWheelZoom]);

  useLayoutEffect(() => {
    const pendingAnchor = pendingZoomAnchorRef.current;
    const scroller = scrollRef.current;
    if (!pendingAnchor || !scroller) {
      return;
    }

    scroller.scrollLeft = Math.max(0, msToPx(pendingAnchor.anchorMs, currentZoom) - pendingAnchor.viewportX);
    setTimelineScrollLeft(scroller.scrollLeft);
    pendingZoomAnchorRef.current = null;
  }, [currentZoom, timelineWidthPx]);

  useEffect(() => {
    if (!activeFile || activeClips.length === 0 || timelineViewportWidth <= 0) {
      return;
    }

    const nextZoom = Math.min(DEFAULT_ZOOM, fitZoom);
    if (Math.abs(activeFile.zoom - DEFAULT_ZOOM) < 0.001 && activeFile.zoom > nextZoom + 0.001) {
      dispatch({ type: 'set-zoom', zoom: nextZoom });
    }
  }, [activeClips.length, activeFile, fitZoom, timelineViewportWidth]);

  const seekTimelineFromClientX = useCallback((clientX: number, surfaceLeft: number, preservePlayback: boolean, commit = false) => {
    const scroller = scrollRef.current;
    if (!scroller) {
      return;
    }

    const localX = Math.max(0, clientX - surfaceLeft + scroller.scrollLeft);
    seekTo(pxToMs(localX, zoomRef.current), preservePlayback, commit);
  }, [seekTo]);

  const handleTimelineScrubStart = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0 || !activeFile || !scrollRef.current) {
      return;
    }

    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);

    const surfaceLeft = event.currentTarget.getBoundingClientRect().left;
    const preservePlayback = activeFile.isPlaying;

    if (activeFile.selectedClipIds.length > 0) {
      dispatch({ type: 'set-selection', clipIds: [] });
    }

    seekTimelineFromClientX(event.clientX, surfaceLeft, preservePlayback, false);
    setTimelineScrub({
      pointerId: event.pointerId,
      surfaceLeft,
      preservePlayback,
    });
  };

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
    if (!timelineScrub) {
      return undefined;
    }

    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerId !== timelineScrub.pointerId) {
        return;
      }

      seekTimelineFromClientX(event.clientX, timelineScrub.surfaceLeft, timelineScrub.preservePlayback, false);
    };

    const handlePointerUp = (event: PointerEvent) => {
      if (event.pointerId !== timelineScrub.pointerId) {
        return;
      }

      seekTimelineFromClientX(event.clientX, timelineScrub.surfaceLeft, timelineScrub.preservePlayback, true);
      setTimelineScrub(null);
    };

    const handlePointerCancel = (event: PointerEvent) => {
      if (event.pointerId !== timelineScrub.pointerId) {
        return;
      }

      seekTo(livePlayheadMsRef.current, timelineScrub.preservePlayback, true);
      setTimelineScrub(null);
    };

    const cancelScrub = () => {
      seekTo(livePlayheadMsRef.current, timelineScrub.preservePlayback, true);
      setTimelineScrub(null);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerCancel);
    window.addEventListener('blur', cancelScrub);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerCancel);
      window.removeEventListener('blur', cancelScrub);
    };
  }, [seekTimelineFromClientX, seekTo, timelineScrub]);

  useEffect(() => {
    if (!interaction || !activeFile) {
      return undefined;
    }

    const handlePointerMove = (event: PointerEvent) => {
      if (interaction.type === 'move') {
        const deltaMs = pxToMs(event.clientX - interaction.startClientX, activeFile.zoom);
        setInteraction({
          ...interaction,
          previewStartMs: Math.max(0, interaction.originStartMs + deltaMs),
        });
        return;
      }

      if (interaction.type === 'trim-start') {
        const clip = activeFile.clips.find((candidate) => candidate.id === interaction.clipId);
        if (!clip) {
          return;
        }

        const deltaMs = pxToMs(event.clientX - interaction.startClientX, activeFile.zoom);
        setInteraction({
          ...interaction,
          previewInPointMs: clamp(
            interaction.originInPointMs + deltaMs,
            0,
            clip.outPointMs - MIN_CLIP_DURATION_MS,
          ),
        });
        return;
      }

      const clip = activeFile.clips.find((candidate) => candidate.id === interaction.clipId);
      if (!clip) {
        return;
      }

      const deltaMs = pxToMs(event.clientX - interaction.startClientX, activeFile.zoom);
      setInteraction({
        ...interaction,
        previewOutPointMs: clamp(
          interaction.originOutPointMs + deltaMs,
          clip.inPointMs + MIN_CLIP_DURATION_MS,
          activeFile.asset.durationMs,
        ),
      });
    };

    const handlePointerUp = () => {
      if (interaction.type === 'move') {
        dispatch({
          type: 'move-clip',
          clipId: interaction.clipId,
          startMs: interaction.previewStartMs,
        });
      }

      if (interaction.type === 'trim-start') {
        dispatch({
          type: 'trim-clip-start',
          clipId: interaction.clipId,
          inPointMs: interaction.previewInPointMs,
        });
      }

      if (interaction.type === 'trim-end') {
        dispatch({
          type: 'trim-clip-end',
          clipId: interaction.clipId,
          outPointMs: interaction.previewOutPointMs,
        });
      }

      setInteraction(null);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp, { once: true });

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [activeFile, interaction]);

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
    anchorTimeMs: Math.max(0, Math.round(lprSelectedTargetAnchor?.timeMs ?? livePlayheadMsRef.current)),
    playheadMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
  }), [activeFile, canAnalyzeRange, lprRuntimeStatus, lprSelectedTargetAnchor, lprState, lprTopCandidate, state.workspaceName]);

  const buildAiPanelWindowSnapshot = useCallback((): AiPanelSessionSnapshot => ({
    workspaceName: state.workspaceName,
    activeFileName: activeFile?.asset.name ?? null,
    hasActiveFile: Boolean(activeFile),
    runtimeStatus: lprRuntimeStatus,
    lpr: lprState,
    ai: aiState,
    playheadMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
  }), [activeFile, aiState, lprRuntimeStatus, lprState, state.workspaceName]);

  const updateAiJob = useCallback((fileId: string, job: Partial<typeof aiState.job>) => {
    dispatch({
      type: 'set-ai-job',
      fileId,
      job: {
        ...job,
        updatedAt: new Date().toISOString(),
      },
    });
  }, [dispatch]);

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
      currentToolName: null,
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
    const projectedSelectedTrack = projectedTargetTracks.find((track) => track.id === selectedTargetTrackId) ?? null;
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
        currentToolName: null,
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
      dispatch({ type: 'accept-lpr-candidate', candidateId: response.acceptedCandidateId ?? null });
      dispatch({ type: 'set-lpr-provenance', provenance: response.provenance ?? null });
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
    const sampleDivisor = lprState.useDenseSampling ? 16 : 8;
    const sampleEveryMs = Math.max(120, Math.round((interval.endMs - interval.startMs) / sampleDivisor) || 120);

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
        sampleEveryMs,
        maxSamples: lprState.useDenseSampling ? 18 : 8,
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
      dispatch({ type: 'accept-lpr-candidate', candidateId: response.acceptedCandidateId ?? null });
      dispatch({ type: 'set-lpr-provenance', provenance: response.provenance ?? null });
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
    const targetTrack = lprState.targetTracks.find((track) => track.id === targetTrackId) ?? null;
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
        acceptedCandidate: lprAcceptedCandidate,
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
        currentToolName: event.payload.stage,
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
  }, [handleExportWindowSessionRequest]);

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

  const rulerStepMs = useMemo(() => rulerStepForZoom(currentZoom), [currentZoom]);
  const rulerTicks = useMemo(() => {
    const paddingPx = Math.max(timelineVisibleWidthPx, 240);
    const visibleStartMs = pxToMs(Math.max(0, timelineScrollLeft - paddingPx), currentZoom);
    const visibleEndMs = Math.min(
      timelineRangeEndMs + rulerStepMs,
      pxToMs(timelineScrollLeft + timelineVisibleWidthPx + paddingPx, currentZoom),
    );
    const startMs = Math.max(0, Math.floor(visibleStartMs / rulerStepMs) * rulerStepMs);
    const endMs = Math.ceil(visibleEndMs / rulerStepMs) * rulerStepMs;
    const ticks: number[] = [];
    for (let current = startMs; current <= endMs; current += rulerStepMs) {
      ticks.push(Math.round(current));
    }
    return ticks;
  }, [currentZoom, rulerStepMs, timelineRangeEndMs, timelineScrollLeft, timelineVisibleWidthPx]);

  const timelineClips = useMemo(() => {
    return activeClips.map((clip) => {
      const activeInteraction = interaction && interaction.clipId === clip.id ? interaction : null;
      const currentStartMs = activeInteraction?.type === 'move'
        ? activeInteraction.previewStartMs
        : activeInteraction?.type === 'trim-start'
          ? clip.startMs + (activeInteraction.previewInPointMs - clip.inPointMs)
          : clip.startMs;
      const currentInPointMs = activeInteraction?.type === 'trim-start'
        ? activeInteraction.previewInPointMs
        : clip.inPointMs;
      const currentOutPointMs = activeInteraction?.type === 'trim-end'
        ? activeInteraction.previewOutPointMs
        : clip.outPointMs;

      return {
        clip,
        leftPx: msToPx(currentStartMs, currentZoom),
        widthPx: Math.max(28, msToPx(currentOutPointMs - currentInPointMs, currentZoom)),
      };
    });
  }, [activeClips, currentZoom, interaction]);

  const markerStyle = activeFile?.markerRect ? {
    left: `${previewViewport.left + (activeFile.markerRect.x * previewViewport.width)}px`,
    top: `${previewViewport.top + (activeFile.markerRect.y * previewViewport.height)}px`,
    width: `${activeFile.markerRect.width * previewViewport.width}px`,
    height: `${activeFile.markerRect.height * previewViewport.height}px`,
  } : undefined;

  const timelineCanvasStyle = {
    width: `${timelineWidthPx + TIMELINE_LABEL_WIDTH_PX}px`,
    '--timeline-label-width': `${TIMELINE_LABEL_WIDTH_PX}px`,
    '--timeline-width': `${timelineWidthPx}px`,
    '--playhead-left': `${msToPx(displayPlayheadMs, currentZoom)}px`,
  } as React.CSSProperties;

  return (
    <div className={styles.editor}>
      <section className={styles.toolbar}>
        <div className={styles.toolbarActions}>
          <button
            type="button"
            className={styles.toolbarButton}
            onClick={() => void handleExportCurrentFrame()}
            disabled={!activeFile || activeFile.asset.status !== 'ready'}
          >
            <ImageDown size={14} />
            Frame
          </button>
          <button type="button" className={styles.toolbarButton} onClick={() => void handleOpenExportWindow()}>
            <FileOutput size={14} />
            Export
          </button>
          <button type="button" className={styles.toolbarButton} onClick={() => void handleOpenPlateWindow()}>
            <Target size={14} />
            Plate
          </button>
          <button type="button" className={styles.toolbarButton} onClick={() => void handleOpenAiPanelWindow()}>
            <Brain size={14} />
            AI
          </button>
          <button
            type="button"
            className={`${styles.toolbarButton} ${activeFile?.renderProfile.compressionMode === 'compact' ? styles.toolbarButtonActive : ''}`}
            onClick={handleToggleCompactExports}
            disabled={!activeFile}
          >
            <Archive size={14} />
            Compact
          </button>
          <button type="button" className={styles.primaryButton} onClick={() => void handleImportClick()}>
            <Import size={14} />
            Import
          </button>
        </div>
      </section>

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
        <aside className={styles.binPanel}>
          {isExternalDropActive && (
            <div className={styles.dropOverlay}>
              <div className={styles.dropOverlayContent}>
                <Import size={32} />
                <strong>Drop Videos Here</strong>
              </div>
            </div>
          )}

          <div className={styles.panelHeader}>
            <h2>Files</h2>
            <span className={styles.badge}>{state.files.length}</span>
          </div>

          {missingFiles.length > 0 && (
            <div className={styles.missingSummary}>
              <AlertCircle size={15} />
              <span>{missingFiles.length} file(s) missing. Relink them before playback or export.</span>
            </div>
          )}

          <div className={styles.assetList}>
            {state.files.length === 0 && (
              <button type="button" className={styles.emptyState} onClick={() => void handleImportClick()}>
                <Import size={20} />
              </button>
            )}

            {state.files.map((fileState) => (
              <div
                key={fileState.id}
                className={`${styles.assetCard} ${fileState.asset.status === 'missing' ? styles.assetCardMissing : ''} ${state.activeFileId === fileState.id ? styles.assetCardSelected : ''}`}
              >
                <button
                  type="button"
                  className={styles.assetDragButton}
                  onClick={() => handleSelectFile(fileState.id)}
                >
                  <div className={styles.assetVisual}>
                    {fileState.asset.thumbnailUrl ? (
                      <img src={fileState.asset.thumbnailUrl} alt={fileState.asset.name} />
                    ) : (
                      <div className={styles.assetFallback}>
                        <Film size={16} />
                      </div>
                    )}
                  </div>
                  <div className={styles.assetMeta}>
                    <strong>{fileState.asset.name}</strong>
                    <span>{formatTransportTime(fileState.asset.durationMs)}</span>
                    <span>{fileState.asset.status === 'missing' ? 'Missing file' : `${fileState.clips.length} segment(s)`}</span>
                  </div>
                </button>

                <div className={styles.assetActions}>
                  {fileState.asset.status === 'missing' ? (
                    <button type="button" className={styles.iconButton} onClick={() => void handleRelinkFile(fileState.id)}>
                      <Link2 size={14} />
                    </button>
                  ) : null}
                  <button type="button" className={styles.iconButton} onClick={() => handleRemoveFile(fileState.id)}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </aside>

        <main className={styles.mainPanel}>
          <section className={styles.previewPanel}>
            <div ref={previewContainerRef} className={styles.previewContainer}>
              <video
                ref={previewVideoRef}
                className={`${styles.previewVideo} ${!previewState.hasActiveVideo ? styles.previewVideoHidden : ''}`}
                playsInline
                preload="auto"
              />

              {!previewState.hasActiveVideo && (
                <div className={styles.previewPlaceholder}>
                  <Film size={32} />
                </div>
              )}

              {activeFile && previewViewport.width > 0 && (
                <div className={styles.previewMarkerLayer}>
                  <LprPreviewOverlayLayer
                    ref={lprOverlayLayerRef}
                    previewViewport={previewViewport}
                    targetTracks={lprState.targetTracks}
                    analysisTrack={lprAnalysisTrack}
                    selectedTargetTrackId={lprState.selectedTargetTrackId}
                    basePlayheadMs={currentPlayheadMs}
                    onSelectTrack={handleSelectTargetTrack}
                  />
                  {activeFile.markerRect && markerStyle && (
                    <div
                      className={styles.previewMarker}
                      style={markerStyle}
                      onPointerDown={handleMarkerPointerDown}
                    >
                      <button
                        type="button"
                        className={styles.previewMarkerResize}
                        onPointerDown={handleMarkerResizePointerDown}
                        aria-label="Resize marker"
                      />
                    </div>
                  )}
                </div>
              )}

              <div className={styles.previewTools}>
                <button type="button" className={styles.previewToolButton} onClick={handleCreateMarker} disabled={!activeFile}>
                  <Square size={14} />
                  {activeFile?.markerRect ? 'Marker' : 'Add Marker'}
                </button>
                <button type="button" className={styles.previewToolButton} onClick={() => dispatch({ type: 'clear-marker' })} disabled={!activeFile?.markerRect}>
                  <X size={14} />
                  Clear
                </button>
              </div>
            </div>
          </section>

          <div className={styles.transportRow}>
            <div className={styles.transportLeftGroup}>
              <div className={styles.transportTime}>
                <span ref={currentTimecodeRef} className={styles.timecode}>{formatRulerLabel(displayPlayheadMs)}</span>
                <span className={styles.timecodeDivider}>/</span>
                <span className={styles.timecodeDuration}>{formatRulerLabel(timelineDurationMs)}</span>
              </div>
              <div className={styles.toolbarDivider} />
              <div className={styles.timelineActions}>
                <button
                  type="button"
                  className={`${styles.iconButton} ${trackMuted ? styles.iconButtonActive : ''}`}
                  onClick={() => dispatch({ type: 'set-track-muted', muted: !trackMuted })}
                  disabled={!activeFile || activeClips.length === 0}
                  aria-pressed={trackMuted}
                  aria-label={trackMuted ? 'Unmute track' : 'Mute track'}
                >
                  {trackMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
                </button>
                <button
                  type="button"
                  className={styles.iconButton}
                  onClick={() => dispatch({ type: 'split-clip', clipId: selectedClip?.id ?? '', atMs: livePlayheadMsRef.current })}
                  disabled={!selectedClip}
                  aria-label="Split selected clip"
                >
                  <Scissors size={14} />
                </button>
                <button
                  type="button"
                  className={styles.iconButton}
                  onClick={() => dispatch({ type: 'delete-selected-clips' })}
                  disabled={!selectedClip}
                  aria-label="Delete selected clip"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>

            <div className={styles.transportButtons}>
              <button
                type="button"
                className={styles.iconButton}
                onClick={() => seekBy(-1000)}
                disabled={timelineDurationMs === 0}
                aria-label="Seek backward one second"
              >
                <SkipBack size={16} />
              </button>
              <button
                type="button"
                className={styles.transportPrimary}
                onClick={togglePlay}
                disabled={timelineDurationMs === 0}
                aria-label={currentIsPlaying ? 'Pause playback' : 'Start playback'}
              >
                {currentIsPlaying ? <Pause size={18} /> : <Play size={18} className={styles.playIconOffset} />}
              </button>
              <button
                type="button"
                className={styles.iconButton}
                onClick={() => seekBy(1000)}
                disabled={timelineDurationMs === 0}
                aria-label="Seek forward one second"
              >
                <SkipForward size={16} />
              </button>
            </div>

            <div className={styles.volumeGroup}>
              <button
                type="button"
                className={styles.iconButton}
                onClick={() => dispatch({ type: 'set-preview-muted', previewMuted: !currentPreviewMuted })}
                disabled={!activeFile}
                aria-label={currentPreviewMuted ? 'Unmute preview' : 'Mute preview'}
              >
                {currentPreviewMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              </button>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={currentPreviewVolume}
                onChange={(event) =>
                  dispatch({
                    type: 'set-preview-volume',
                    previewVolume: Number(event.target.value),
                  })}
                disabled={!activeFile}
                aria-label="Adjust preview volume"
                className={styles.volumeSlider}
              />
            </div>
          </div>

          <section className={styles.timelinePanel}>
            <div className={styles.timelineScroller} ref={scrollRef}>
              <div
                ref={timelineCanvasRef}
                className={styles.timelineCanvas}
                style={timelineCanvasStyle}
              >
                <div className={styles.rulerRow}>
                  <div className={styles.stickyCell}>
                    <span className={styles.rulerLabel}>Timeline</span>
                    <span className={styles.rulerMeta}>{formatRulerLabel(rulerStepMs)}</span>
                  </div>
                  <button type="button" className={styles.rulerSurface} onPointerDown={handleTimelineScrubStart}>
                    {rulerTicks.map((tickMs) => (
                      <div key={tickMs} className={styles.rulerTick} style={{ left: `${msToPx(tickMs, currentZoom)}px` }}>
                        <span>{formatRulerLabel(tickMs)}</span>
                      </div>
                    ))}
                    <div className={styles.playhead} />
                  </button>
                </div>

                <div className={styles.trackRow}>
                  <div className={styles.stickyCell}>
                    <div className={styles.trackLabelBlock}>
                      <span>{activeClips.length} clip(s)</span>
                    </div>
                    <span className={styles.trackHint}>{activeFile ? formatTransportTime(activeFile.asset.durationMs) : '--:--'}</span>
                  </div>
                  <div
                    className={styles.trackLane}
                    onPointerDown={handleTimelineScrubStart}
                    style={{ '--grid-step': `${msToPx(rulerStepMs, currentZoom)}px` } as React.CSSProperties}
                  >
                    <div className={styles.playhead} />
                    {timelineClips.map(({ clip, leftPx, widthPx }) => (
                      <div
                        key={clip.id}
                        className={`${styles.clip} ${activeFile?.selectedClipIds.includes(clip.id) ? styles.clipSelected : ''} ${clip.muted ? styles.clipMuted : ''}`}
                        style={{ left: `${leftPx}px`, width: `${widthPx}px` }}
                        role="button"
                        tabIndex={0}
                        aria-pressed={activeFile?.selectedClipIds.includes(clip.id)}
                        onPointerDown={(event) => handleClipPointerDown(event, clip)}
                      >
                        <button
                          type="button"
                          className={`${styles.trimHandle} ${styles.trimHandleStart}`}
                          onPointerDown={(event) => handleTrimStartPointerDown(event, clip)}
                        />
                        <div className={styles.clipBody}>
                          <span className={styles.clipIcon}><Film size={12} /></span>
                          <span className={styles.clipText}>{activeFile?.asset.name ?? 'Clip'}</span>
                          <span className={styles.clipDuration}>{formatTransportTime(clipDurationMs(clip))}</span>
                        </div>
                        <button
                          type="button"
                          className={`${styles.trimHandle} ${styles.trimHandleEnd}`}
                          onPointerDown={(event) => handleTrimEndPointerDown(event, clip)}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>
        </main>
      </div>

    </div>
  );
};
