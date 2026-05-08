import React, { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import { open, save } from '@tauri-apps/plugin-dialog';
import {
  AlertCircle,
  FileOutput,
  FilePlus2,
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
import { editorReducer, initialEditorState } from '../application/editorReducer';
import {
  buildDefaultLprState,
  clamp,
  clipDurationMs,
  createId,
  DEFAULT_MARKER_RECT,
  DEFAULT_ZOOM,
  findClipAtPlayhead,
  formatRulerLabel,
  formatTransportTime,
  getActiveFile,
  getTimelineDuration,
  MAX_ZOOM,
  MIN_CLIP_DURATION_MS,
  MIN_ZOOM,
  msToPx,
  pxToMs,
  type EditorAsset,
  type EditorFileState,
  type TimelineClip,
  type VideoMarkerRect,
} from '../domain/model';
import {
  buildEditorAsset,
  exportFrameImage,
  isSupportedMediaPath,
} from '../infrastructure/mediaApi';
import {
  analyzeLprFrame,
  analyzeLprInterval,
  exportLprEvidence,
  getLprRuntimeStatus,
  scanLprTargets,
} from '../infrastructure/lprApi';
import { createLogger, getErrorMessage, serializeError } from '../../../utils/logger';
import { openExportWindow } from '../../export/infrastructure/exportApi';
import { preparePendingExportSession } from '../../export/application/exportSession';
import {
  PLATE_ACTION_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  type PlateWindowAction,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';
import { emitPlateWindowSession, openPlateWindow } from '../infrastructure/plateWindowApi';
import type {
  LprRuntimeStatus,
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
import styles from './MediaEditorWorkspace.module.css';

const log = createLogger('MediaEditorWorkspace');

const RULER_STEP_CANDIDATES_MS = [1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000];
const MIN_TIMELINE_PADDING_MS = 60000;

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

interface PreviewViewport {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface MediaEditorWorkspaceProps {
  isActive?: boolean;
}

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

function defaultFrameFileName(fileState: EditorFileState, playheadMs: number) {
  const baseName = replaceExtension(fileState.asset.name, 'png');
  const timeLabel = formatTransportTime(playheadMs).replace(/[:.]/g, '-');
  return replaceExtension(baseName, `${timeLabel}.png`);
}

function defaultLprEvidenceFileName(fileState: EditorFileState, playheadMs: number, candidateText: string | null) {
  const baseName = replaceExtension(fileState.asset.name, 'json');
  const timeLabel = formatTransportTime(playheadMs).replace(/[:.]/g, '-');
  const candidateLabel = candidateText ? `_${candidateText}` : '';
  return replaceExtension(baseName, `${timeLabel}${candidateLabel}.json`);
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

function getClosestTrackFrame(track: LprTargetTrack, playheadMs: number, toleranceMs = 360) {
  if (track.frames.length === 0) {
    return null;
  }

  const frame = track.frames.reduce((closestFrame, candidate) => {
    const closestDelta = Math.abs(closestFrame.timeMs - playheadMs);
    const candidateDelta = Math.abs(candidate.timeMs - playheadMs);
    return candidateDelta < closestDelta ? candidate : closestFrame;
  });

  return Math.abs(frame.timeMs - playheadMs) <= toleranceMs ? frame : null;
}

function normalizeLprInterval(interval: TimelineIntervalSelection): TimelineIntervalSelection {
  const startMs = Math.max(0, Math.round(interval.startMs));
  const endMs = Math.max(0, Math.round(interval.endMs));

  return {
    startMs: Math.min(startMs, endMs),
    endMs: Math.max(startMs, endMs),
  };
}

export const MediaEditorWorkspace: React.FC<MediaEditorWorkspaceProps> = ({ isActive = true }) => {
  const [state, dispatch] = useReducer(editorReducer, initialEditorState);
  const [workspaceFeedback, setWorkspaceFeedback] = useState<string | null>(null);
  const [importFeedback, setImportFeedback] = useState<string | null>(null);
  const [lprRuntimeStatus, setLprRuntimeStatus] = useState<LprRuntimeStatus | null>(null);
  const [isExternalDropActive, setIsExternalDropActive] = useState(false);
  const [timelineViewportWidth, setTimelineViewportWidth] = useState(0);
  const [timelineScrollLeft, setTimelineScrollLeft] = useState(0);
  const [interaction, setInteraction] = useState<ClipInteraction | null>(null);
  const [markerInteraction, setMarkerInteraction] = useState<MarkerInteraction | null>(null);
  const [previewViewport, setPreviewViewport] = useState<PreviewViewport>({ left: 0, top: 0, width: 0, height: 0 });
  const [livePreviewState, setLivePreviewState] = useState<PlaybackPreviewState>({
    previewAsset: null,
    hasActiveVideo: false,
  });
  const [liveOverlayPlayheadMs, setLiveOverlayPlayheadMs] = useState(0);

  const zoomRef = useRef(DEFAULT_ZOOM);
  const pendingZoomAnchorRef = useRef<{ anchorMs: number; viewportX: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const timelineCanvasRef = useRef<HTMLDivElement>(null);
  const previewContainerRef = useRef<HTMLDivElement>(null);
  const previewVideoRef = useRef<HTMLVideoElement>(null);
  const currentTimecodeRef = useRef<HTMLSpanElement>(null);
  const livePlayheadMsRef = useRef(0);
  const latestCountryHintDraftRef = useRef<string | null>(null);

  const activeFile = useMemo(() => getActiveFile(state), [state]);
  const lprState = useMemo(() => activeFile?.lpr ?? buildDefaultLprState(), [activeFile]);
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
    () => Math.max(240, timelineViewportWidth - 8),
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
  const previewState = currentIsPlaying ? livePreviewState : committedPreviewState;
  const lprPreviewPlayheadMs = currentIsPlaying ? liveOverlayPlayheadMs : currentPlayheadMs;
  const missingFiles = useMemo(
    () => state.files.filter((fileState) => fileState.asset.status === 'missing'),
    [state.files],
  );
  const lprJob = lprState.job;
  const lprBusy = lprJob.status === 'queued' || lprJob.status === 'running';
  const lprSelectedTrack = useMemo(
    () => lprState.targetTracks.find((track) => track.id === lprState.selectedTargetTrackId) ?? null,
    [lprState.selectedTargetTrackId, lprState.targetTracks],
  );
  const lprSelectedTrackFrame = useMemo(
    () => (lprSelectedTrack ? getClosestTrackFrame(lprSelectedTrack, lprPreviewPlayheadMs) : null),
    [lprPreviewPlayheadMs, lprSelectedTrack],
  );
  const lprOverlayTracks = useMemo(
    () => lprState.targetTracks
      .map((track) => ({
        track,
        frame: getClosestTrackFrame(track, lprPreviewPlayheadMs),
      }))
      .filter((entry): entry is { track: LprTargetTrack; frame: LprTrackedRegion } => Boolean(entry.frame)),
    [lprPreviewPlayheadMs, lprState.targetTracks],
  );
  const lprTopCandidate = lprState.candidates.find((candidate) => candidate.id === lprState.acceptedCandidateId)
    ?? lprState.candidates[0]
    ?? null;
  const canAnalyzeRange = Boolean(activeFile && !lprBusy && lprSelectedTrackFrame && lprState.interval);

  useEffect(() => {
    setLiveOverlayPlayheadMs(currentPlayheadMs);
  }, [activeFile?.id, currentPlayheadMs]);

  const refreshLprRuntimeStatus = useCallback(async () => {
    try {
      const runtimeStatus = await getLprRuntimeStatus();
      setLprRuntimeStatus(runtimeStatus);
    } catch (error) {
      setLprRuntimeStatus({
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

  const updateLprJob = useCallback((job: Partial<EditorFileState['lpr']['job']>) => {
    dispatch({
      type: 'set-lpr-job',
      job: {
        ...job,
        updatedAt: new Date().toISOString(),
      },
    });
  }, [dispatch]);

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
    React.startTransition(() => {
      setLiveOverlayPlayheadMs(playheadMs);
    });

    if (currentTimecodeRef.current) {
      currentTimecodeRef.current.textContent = formatTransportTime(playheadMs);
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
    const cursorX = clamp(event.clientX - bounds.left, 0, timelineVisibleWidthPx);
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
        setImportFeedback(
          failures[0].reason instanceof Error
            ? failures[0].reason.message
            : `${failures.length} file(s) failed to import.`,
        );
      }
    } catch (error) {
      setImportFeedback(error instanceof Error ? error.message : 'Failed to import media.');
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

  const handleResetWorkspace = () => {
    if (state.files.length > 0 && !window.confirm('Clear the current workspace? This cannot be saved.')) {
      return;
    }

    stopPlayback();
    dispatch({ type: 'reset-workspace' });
    setWorkspaceFeedback(null);
    setImportFeedback(null);
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
      await openExportWindow(snapshot);
    } catch (error) {
      log.error('Failed to open export window.', {
        error: serializeError(error),
        fileCount: state.files.length,
      });
      setWorkspaceFeedback(getErrorMessage(error, 'Failed to open export window.'));
    }
  };

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

    const selectedPath = await save({
      title: 'Export current frame',
      defaultPath: defaultFrameFileName(fileState, playheadMs),
      filters: [{ name: 'PNG Image', extensions: ['png'] }],
    });

    if (!selectedPath) {
      return;
    }

    const outputPath = selectedPath.toLowerCase().endsWith('.png') ? selectedPath : `${selectedPath}.png`;
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
      });
      setWorkspaceFeedback(`Frame exported to ${outputPath}`);
    } catch (error) {
      setWorkspaceFeedback(getErrorMessage(error, 'Failed to export the current frame.'));
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
      setImportFeedback(error instanceof Error ? error.message : 'Failed to relink video.');
    }
  };

  const handleTimelineSeek = (event: React.PointerEvent<HTMLElement>) => {
    if (!activeFile || !scrollRef.current) {
      return;
    }

    const bounds = scrollRef.current.getBoundingClientRect();
    const localX = event.clientX - bounds.left + scrollRef.current.scrollLeft;
    seekTo(pxToMs(localX, activeFile.zoom), activeFile.isPlaying);
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
    anchorTimeMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
  }), [activeFile, canAnalyzeRange, lprRuntimeStatus, lprState, lprTopCandidate, state.workspaceName]);

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

    updateLprJob({
      status: 'running',
      progress: 0.18,
      stage: 'Targets',
      detail: 'Scanning current frame for trackable targets.',
      error: null,
      startedAt: new Date().toISOString(),
    });

    try {
      const response = await scanLprTargets({
        sourcePath: activeFile.asset.path,
        timeMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
        markerRect: activeFile.markerRect,
        targetVehicleKind: lprState.targetVehicleKind,
      });

      setLprRuntimeStatus(response.runtime);
      dispatch({ type: 'set-lpr-target-tracks', targetTracks: buildTargetTracksFromDetections(response.detections) });
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
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Targets',
        detail: 'Target scan failed.',
        error: getErrorMessage(error, 'Unable to scan targets.'),
      });
      setWorkspaceFeedback(getErrorMessage(error, 'Unable to scan targets.'));
    }
  };

  const handleAnalyzeLprFrame = async () => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    const countryHints = applyCountryHints(
      latestCountryHintDraftRef.current ?? (activeFile.lpr.countryHints.join(', ')),
    );
    updateLprJob({
      status: 'running',
      progress: 0.24,
      stage: 'Frame',
      detail: 'Analyzing the current frame.',
      error: null,
      startedAt: new Date().toISOString(),
    });

    try {
      const response = await analyzeLprFrame({
        sourcePath: activeFile.asset.path,
        timeMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
        markerRect: activeFile.markerRect,
        targetVehicleKind: lprState.targetVehicleKind,
        selectedTargetBox: lprSelectedTrackFrame?.box ?? null,
        countryHints,
      });

      setLprRuntimeStatus(response.runtime);
      dispatch({ type: 'set-lpr-target-tracks', targetTracks: buildTargetTracksFromDetections(response.detections) });
      dispatch({ type: 'set-lpr-samples', samples: response.sample ? [response.sample] : [] });
      dispatch({ type: 'set-lpr-candidates', candidates: response.candidates });
      dispatch({ type: 'accept-lpr-candidate', candidateId: response.candidates[0]?.id ?? null });
      if (response.candidates.length > 0) {
        dispatch({
          type: 'append-lpr-history',
          entry: {
            id: createId('lpr-history'),
            createdAt: new Date().toISOString(),
            interval: null,
            targetTrackId: response.detections[0]?.id ?? null,
            acceptedCandidateId: response.candidates[0]?.id ?? null,
            candidates: response.candidates,
            summary: response.candidates[0]?.text ?? 'Frame analysis',
          },
        });
      }
      updateLprJob({
        status: 'completed',
        progress: 1,
        stage: 'Frame',
        detail: response.candidates[0]
          ? `Best candidate ${response.candidates[0].text}`
          : 'No confident plate candidate.',
      });
    } catch (error) {
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Frame',
        detail: 'Frame analysis failed.',
        error: getErrorMessage(error, 'Unable to analyze the current frame.'),
      });
      setWorkspaceFeedback(getErrorMessage(error, 'Unable to analyze the current frame.'));
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

    if (!lprSelectedTrackFrame) {
      const errorMessage = 'Select a target on the current frame before running Range.';
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
    const countryHints = applyCountryHints(
      latestCountryHintDraftRef.current ?? (activeFile.lpr.countryHints.join(', ')),
    );
    const sampleDivisor = lprState.useDenseSampling ? 16 : 8;
    const sampleEveryMs = Math.max(120, Math.round((interval.endMs - interval.startMs) / sampleDivisor) || 120);

    updateLprJob({
      status: 'running',
      progress: 0.12,
      stage: 'Interval',
      detail: 'Tracking the selected target across the chosen interval.',
      error: null,
      startedAt: new Date().toISOString(),
    });

    try {
      const response = await analyzeLprInterval({
        sourcePath: activeFile.asset.path,
        interval,
        anchorTimeMs: Math.max(0, Math.round(livePlayheadMsRef.current)),
        targetVehicleKind: lprState.targetVehicleKind,
        selectedTargetBox: lprSelectedTrackFrame.box,
        countryHints,
        sampleEveryMs,
        maxSamples: lprState.useDenseSampling ? 18 : 8,
      });

      setLprRuntimeStatus(response.runtime);
      dispatch({ type: 'set-lpr-interval', interval });
      dispatch({ type: 'set-lpr-target-tracks', targetTracks: response.targetTracks });
      dispatch({ type: 'set-lpr-samples', samples: response.samples });
      dispatch({ type: 'set-lpr-candidates', candidates: response.candidates });
      dispatch({ type: 'accept-lpr-candidate', candidateId: response.acceptedCandidateId ?? response.candidates[0]?.id ?? null });
      dispatch({
        type: 'append-lpr-history',
        entry: {
          id: createId('lpr-history'),
          createdAt: new Date().toISOString(),
          interval,
          targetTrackId: response.targetTracks[0]?.id ?? null,
          acceptedCandidateId: response.acceptedCandidateId ?? response.candidates[0]?.id ?? null,
          candidates: response.candidates,
          summary: response.summary,
        },
      });
      dispatch({ type: 'set-lpr-mode', workflowMode: response.candidates.length > 0 ? 'review' : 'target' });
      updateLprJob({
        status: 'completed',
        progress: 1,
        stage: 'Interval',
        detail: response.summary,
      });
    } catch (error) {
      updateLprJob({
        status: 'failed',
        progress: 1,
        stage: 'Interval',
        detail: 'Interval analysis failed.',
        error: getErrorMessage(error, 'Unable to analyze the selected interval.'),
      });
      setWorkspaceFeedback(getErrorMessage(error, 'Unable to analyze the selected interval.'));
    }
  };

  const handleSelectTargetTrack = (targetTrackId: string) => {
    dispatch({ type: 'select-lpr-target-track', targetTrackId });
  };

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
        interval: lprState.interval,
        targetTrack: lprSelectedTrack,
        acceptedCandidate: lprTopCandidate,
        candidates: lprState.candidates,
        samples: lprState.samples,
      });

      setWorkspaceFeedback(`Evidence exported to ${response.jsonPath} with frame ${response.imagePath}`);
    } catch (error) {
      setWorkspaceFeedback(getErrorMessage(error, 'Unable to export the LPR evidence snapshot.'));
    }
  };

  const handleOpenPlateWindow = async () => {
    await openPlateWindow();
    await emitPlateWindowSession(buildPlateWindowSnapshot()).catch(() => undefined);
  };

  const handlePlateWindowAction = React.useEffectEvent(async (action: PlateWindowAction) => {
    switch (action.type) {
      case 'refresh-runtime':
        await refreshLprRuntimeStatus();
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
      case 'export-evidence':
        await handleExportLprEvidence();
        break;
      case 'clear-results':
        dispatch({ type: 'clear-lpr-results' });
        break;
      case 'select-target-track':
        handleSelectTargetTrack(action.targetTrackId);
        break;
      case 'accept-candidate':
        dispatch({ type: 'accept-lpr-candidate', candidateId: action.candidateId });
        break;
      default:
        break;
    }
  });

  const handlePlateWindowSessionRequest = React.useEffectEvent(async () => {
    await emitPlateWindowSession(buildPlateWindowSnapshot()).catch(() => undefined);
  });

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
    void emitPlateWindowSession(buildPlateWindowSnapshot()).catch(() => undefined);
  }, [buildPlateWindowSnapshot]);

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

  return (
    <div className={styles.editor}>
      <section className={styles.toolbar}>
        <div className={styles.workspaceMeta}>
          <strong>{state.workspaceName}</strong>
          <span>{state.files.length} file(s)</span>
        </div>

        <div className={styles.toolbarActions}>
          <button type="button" className={styles.toolbarButton} onClick={handleResetWorkspace}>
            <FilePlus2 size={14} />
            New
          </button>
          <div className={styles.toolbarDivider} />
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
                <span>Release to add files into the current workspace</span>
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
                  {lprOverlayTracks.map(({ track, frame }) => {
                    const box = frame.box;
                    const overlayStyle = {
                      left: `${previewViewport.left + (box.x * previewViewport.width)}px`,
                      top: `${previewViewport.top + (box.y * previewViewport.height)}px`,
                      width: `${box.width * previewViewport.width}px`,
                      height: `${box.height * previewViewport.height}px`,
                    };

                    return (
                      <button
                        key={track.id}
                        type="button"
                        className={`${styles.lprOverlayTarget} ${track.id === lprState.selectedTargetTrackId ? styles.lprOverlayTargetSelected : ''}`}
                        style={overlayStyle}
                        onClick={() => handleSelectTargetTrack(track.id)}
                      >
                        <span className={styles.lprOverlayLabel}>{track.label}</span>
                      </button>
                    );
                  })}
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

              <div className={styles.transportOverlay}>
                <div className={styles.transportTime}>
                  <span ref={currentTimecodeRef} className={styles.timecode}>{formatTransportTime(currentPlayheadMs)}</span>
                  <span className={styles.timecodeDivider}>/</span>
                  <span className={styles.timecodeDuration}>{formatTransportTime(timelineDurationMs)}</span>
                </div>

                <div className={styles.transportMainRow}>
                  <div className={styles.volumeGroup}>
                    <button
                      type="button"
                      className={styles.iconButton}
                      onClick={() => dispatch({ type: 'set-preview-muted', previewMuted: !currentPreviewMuted })}
                      disabled={!activeFile}
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
                    />
                  </div>

                  <div className={styles.transportButtons}>
                    <button type="button" className={styles.iconButton} onClick={() => seekBy(-1000)} disabled={timelineDurationMs === 0}>
                      <SkipBack size={16} />
                    </button>
                    <button type="button" className={styles.transportPrimary} onClick={togglePlay} disabled={timelineDurationMs === 0}>
                      {currentIsPlaying ? <Pause size={18} /> : <Play size={18} />}
                    </button>
                    <button type="button" className={styles.iconButton} onClick={() => seekBy(1000)} disabled={timelineDurationMs === 0}>
                      <SkipForward size={16} />
                    </button>
                  </div>

                  <div className={styles.transportSpacer} />
                </div>
              </div>
            </div>
          </section>

          <section className={styles.timelinePanel}>
            <div className={styles.panelHeader}>
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
                >
                  <Scissors size={14} />
                </button>
                <button type="button" className={styles.iconButton} onClick={() => dispatch({ type: 'delete-selected-clips' })} disabled={!selectedClip}>
                  <Trash2 size={14} />
                </button>
                <div className={styles.toolbarDivider} />
                <span className={styles.timelineHint}>Space Play/Pause</span>
                <span className={styles.timelineHint}>S Split</span>
                <span className={styles.timelineHint}>M Clip Mute</span>
                <span className={styles.timelineHint}>Del Delete</span>
              </div>
            </div>

            <div className={styles.timelineScroller} ref={scrollRef}>
              <div
                ref={timelineCanvasRef}
                className={`${styles.timelineCanvas} ${styles.timelineCanvasSingle}`}
                style={{
                  width: `${timelineWidthPx}px`,
                  '--playhead-left': `${msToPx(currentPlayheadMs, currentZoom)}px`,
                } as React.CSSProperties}
              >
                <button type="button" className={`${styles.rulerSurface} ${styles.rulerSurfaceSingle}`} onPointerDown={handleTimelineSeek}>
                  {rulerTicks.map((tickMs) => (
                    <div key={tickMs} className={styles.rulerTick} style={{ left: `${msToPx(tickMs, currentZoom)}px` }}>
                      <span>{formatRulerLabel(tickMs)}</span>
                    </div>
                  ))}
                  <div className={styles.playhead} />
                </button>

                <div
                  className={`${styles.trackLane} ${styles.singleTrackLane}`}
                  onPointerDown={handleTimelineSeek}
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
          </section>
        </main>
      </div>

    </div>
  );
};
