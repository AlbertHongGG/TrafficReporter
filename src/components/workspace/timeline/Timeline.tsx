// src/components/timeline-panel/TimelinePanel.tsx
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Film } from 'lucide-react';
import {
  clamp,
  clipDurationMs,
  DEFAULT_ZOOM,
  formatRulerLabel,
  formatTransportTime,
  MAX_ZOOM,
  MIN_CLIP_DURATION_MS,
  MIN_ZOOM,
  msToPx,
  pxToMs,
  type EditorFileState,
  type TimelineClip,
} from '../../../modules/editor/domain/model';
import type { LiveTransportStore } from '../../../modules/editor/application/liveTransport';
import { useEditorStore } from '../../../modules/editor/application/store/store';
import { editorWorkspaceTransport } from '../../../modules/editor/application/session/editorSessionSync';
import styles from '../MainWorkspace.module.css';

const RULER_STEP_CANDIDATES_MS = [1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000];
const MIN_TIMELINE_PADDING_MS = 60000;
const TIMELINE_LABEL_WIDTH_PX = 120;

function rulerStepForZoom(zoom: number) {
  return (
    RULER_STEP_CANDIDATES_MS.find((stepMs) => msToPx(stepMs, zoom) >= 92)
    ?? RULER_STEP_CANDIDATES_MS.at(-1)
    ?? 1000
  );
}

type ClipInteraction =
  | { type: 'move'; clipId: string; startClientX: number; previewStartMs: number; originStartMs: number; }
  | { type: 'trim-start'; clipId: string; startClientX: number; previewInPointMs: number; originInPointMs: number; }
  | { type: 'trim-end'; clipId: string; startClientX: number; previewOutPointMs: number; originOutPointMs: number; };

type TimelineScrubState = {
  pointerId: number;
  surfaceLeft: number;
  preservePlayback: boolean;
};

export interface TimelinePanelProps {
  activeFile: EditorFileState | null;
  activeClips: TimelineClip[];
  timelineDurationMs: number;
  liveTransportStore: LiveTransportStore;
  seekTo: (timeMs: number, preservePlayback: boolean, commit?: boolean) => void;
  stopPlayback: () => void;
  onScrubStateChange: (isScrubbing: boolean) => void;
}

export const TimelinePanel: React.FC<TimelinePanelProps> = ({
  activeFile,
  activeClips,
  timelineDurationMs,
  liveTransportStore,
  seekTo,
  stopPlayback,
  onScrubStateChange,
}) => {
  const [timelineViewportWidth, setTimelineViewportWidth] = useState(0);
  const [timelineScrollLeft, setTimelineScrollLeft] = useState(0);
  const [interaction, setInteraction] = useState<ClipInteraction | null>(null);
  const [timelineScrub, setTimelineScrub] = useState<TimelineScrubState | null>(null);
  const setZoom = useEditorStore((s) => s.setZoom);
  const setSelection = useEditorStore((s) => s.setSelection);

  const zoomRef = useRef(activeFile?.zoom ?? DEFAULT_ZOOM);
  const pendingZoomAnchorRef = useRef<{ anchorMs: number; viewportX: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const timelineCanvasRef = useRef<HTMLDivElement>(null);

  const currentZoom = activeFile?.zoom ?? DEFAULT_ZOOM;
  const currentPlayheadMs = activeFile?.playheadMs ?? 0;

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

  // Sync zoom ref
  useEffect(() => {
    zoomRef.current = currentZoom;
  }, [currentZoom]);

  // Sync scrub state to parent
  useEffect(() => {
    onScrubStateChange(timelineScrub !== null);
  }, [timelineScrub, onScrubStateChange]);

  // Sync playhead position from live transport store
  useEffect(() => {
    return liveTransportStore.subscribe(() => { const transport = liveTransportStore.getSnapshot();
      if (timelineCanvasRef.current) {
        timelineCanvasRef.current.style.setProperty('--playhead-left', `${msToPx(transport.playheadMs, zoomRef.current)}px`);
      }
    });
  }, [liveTransportStore]);

  // Initialize playhead position
  useEffect(() => {
    const transport = liveTransportStore.getSnapshot();
    if (timelineCanvasRef.current) {
      timelineCanvasRef.current.style.setProperty('--playhead-left', `${msToPx(transport.playheadMs, zoomRef.current)}px`);
    }
  }, [currentZoom, liveTransportStore, timelineWidthPx]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;

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
    if (!event.ctrlKey || !activeFile) return;

    const scroller = scrollRef.current;
    if (!scroller) return;

    event.preventDefault();

    const bounds = scroller.getBoundingClientRect();
    const cursorX = clamp(event.clientX - bounds.left - TIMELINE_LABEL_WIDTH_PX, 0, timelineVisibleWidthPx);
    const currentTimelineZoom = zoomRef.current;
    const cursorTimelineX = Math.max(0, scroller.scrollLeft + cursorX);
    const anchorMs = pxToMs(cursorTimelineX, currentTimelineZoom);
    const nextZoom = clamp(currentTimelineZoom * Math.exp(-event.deltaY * 0.0015), MIN_ZOOM, MAX_ZOOM);

    if (Math.abs(nextZoom - currentTimelineZoom) < 0.001) return;

    zoomRef.current = nextZoom;
    pendingZoomAnchorRef.current = { anchorMs, viewportX: cursorX };
    setZoom(nextZoom);
  }, [activeFile, setZoom, timelineVisibleWidthPx]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;

    const onWheel = (event: WheelEvent) => handleTimelineWheelZoom(event);
    scroller.addEventListener('wheel', onWheel, { passive: false });
    return () => scroller.removeEventListener('wheel', onWheel);
  }, [handleTimelineWheelZoom]);

  useLayoutEffect(() => {
    const pendingAnchor = pendingZoomAnchorRef.current;
    const scroller = scrollRef.current;
    if (!pendingAnchor || !scroller) return;

    scroller.scrollLeft = Math.max(0, msToPx(pendingAnchor.anchorMs, currentZoom) - pendingAnchor.viewportX);
    setTimelineScrollLeft(scroller.scrollLeft);
    pendingZoomAnchorRef.current = null;
  }, [currentZoom, timelineWidthPx]);

  useEffect(() => {
    if (!activeFile || activeClips.length === 0 || timelineViewportWidth <= 0) return;

    const nextZoom = Math.min(DEFAULT_ZOOM, fitZoom);
    if (Math.abs(activeFile.zoom - DEFAULT_ZOOM) < 0.001 && activeFile.zoom > nextZoom + 0.001) {
      setZoom(nextZoom);
    }
  }, [activeClips.length, activeFile, fitZoom, setZoom, timelineViewportWidth]);

  const seekTimelineFromClientX = useCallback((clientX: number, surfaceLeft: number, preservePlayback: boolean, commit = false) => {
    const scroller = scrollRef.current;
    if (!scroller) return;

    const localX = Math.max(0, clientX - surfaceLeft + scroller.scrollLeft);
    seekTo(pxToMs(localX, zoomRef.current), preservePlayback, commit);
  }, [seekTo]);

  const handleTimelineScrubStart = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0 || !activeFile || !scrollRef.current) return;

    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);

    const surfaceLeft = event.currentTarget.getBoundingClientRect().left;
    const preservePlayback = activeFile.isPlaying;

    if (activeFile.selectedClipIds.length > 0) {
      setSelection([]);
    }

    seekTimelineFromClientX(event.clientX, surfaceLeft, preservePlayback, false);
    setTimelineScrub({ pointerId: event.pointerId, surfaceLeft, preservePlayback });
  };

  useEffect(() => {
    if (!timelineScrub) return;

    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerId !== timelineScrub.pointerId) return;
      seekTimelineFromClientX(event.clientX, timelineScrub.surfaceLeft, timelineScrub.preservePlayback, false);
    };

    const handlePointerUp = (event: PointerEvent) => {
      if (event.pointerId !== timelineScrub.pointerId) return;
      seekTimelineFromClientX(event.clientX, timelineScrub.surfaceLeft, timelineScrub.preservePlayback, true);
      setTimelineScrub(null);
    };

    const handlePointerCancel = (event: PointerEvent) => {
      if (event.pointerId !== timelineScrub.pointerId) return;
      const transport = liveTransportStore.getSnapshot();
      seekTo(transport.playheadMs, timelineScrub.preservePlayback, true);
      setTimelineScrub(null);
    };

    const cancelScrub = () => {
      const transport = liveTransportStore.getSnapshot();
      seekTo(transport.playheadMs, timelineScrub.preservePlayback, true);
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
  }, [seekTimelineFromClientX, seekTo, timelineScrub, liveTransportStore]);

  useEffect(() => {
    if (!interaction || !activeFile) return;

    const handlePointerMove = (event: PointerEvent) => {
      if (interaction.type === 'move') {
        const deltaMs = pxToMs(event.clientX - interaction.startClientX, activeFile.zoom);
        setInteraction({ ...interaction, previewStartMs: Math.max(0, interaction.originStartMs + deltaMs) });
        return;
      }
      if (interaction.type === 'trim-start') {
        const clip = activeFile.clips.find((c) => c.id === interaction.clipId);
        if (!clip) return;
        const deltaMs = pxToMs(event.clientX - interaction.startClientX, activeFile.zoom);
        setInteraction({ ...interaction, previewInPointMs: clamp(interaction.originInPointMs + deltaMs, 0, clip.outPointMs - MIN_CLIP_DURATION_MS) });
        return;
      }
      const clip = activeFile.clips.find((c) => c.id === interaction.clipId);
      if (!clip) return;
      const deltaMs = pxToMs(event.clientX - interaction.startClientX, activeFile.zoom);
      setInteraction({ ...interaction, previewOutPointMs: clamp(interaction.originOutPointMs + deltaMs, clip.inPointMs + MIN_CLIP_DURATION_MS, activeFile.asset.durationMs ?? 0) });
    };

    const handlePointerUp = () => {
      if (interaction.type === 'move') {
        editorWorkspaceTransport.moveClip(interaction.clipId, interaction.previewStartMs);
      }
      if (interaction.type === 'trim-start') {
        editorWorkspaceTransport.trimClipStart(interaction.clipId, interaction.previewInPointMs);
      }
      if (interaction.type === 'trim-end') {
        editorWorkspaceTransport.trimClipEnd(interaction.clipId, interaction.previewOutPointMs);
      }
      setInteraction(null);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp, { once: true });
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [activeFile, interaction, setSelection]);

  const handleClipPointerDown = (event: React.PointerEvent<HTMLDivElement>, clip: TimelineClip) => {
    event.stopPropagation();
    stopPlayback();
    setSelection([clip.id]);
    setInteraction({ type: 'move', clipId: clip.id, startClientX: event.clientX, previewStartMs: clip.startMs, originStartMs: clip.startMs });
  };

  const handleTrimStartPointerDown = (event: React.PointerEvent<HTMLButtonElement>, clip: TimelineClip) => {
    event.stopPropagation();
    stopPlayback();
    setSelection([clip.id]);
    setInteraction({ type: 'trim-start', clipId: clip.id, startClientX: event.clientX, previewInPointMs: clip.inPointMs, originInPointMs: clip.inPointMs });
  };

  const handleTrimEndPointerDown = (event: React.PointerEvent<HTMLButtonElement>, clip: TimelineClip) => {
    event.stopPropagation();
    stopPlayback();
    setSelection([clip.id]);
    setInteraction({ type: 'trim-end', clipId: clip.id, startClientX: event.clientX, previewOutPointMs: clip.outPointMs, originOutPointMs: clip.outPointMs });
  };

  const timelineCanvasStyle = {
    width: `${timelineWidthPx + TIMELINE_LABEL_WIDTH_PX}px`,
    '--timeline-label-width': `${TIMELINE_LABEL_WIDTH_PX}px`,
    '--timeline-width': `${timelineWidthPx}px`,
  } as React.CSSProperties;

  return (
    <section className={styles.timelinePanel}>
      <div className={styles.timelineScroller} ref={scrollRef}>
        <div ref={timelineCanvasRef} className={styles.timelineCanvas} style={timelineCanvasStyle}>
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
              <span className={styles.trackHint}>{activeFile ? formatTransportTime(activeFile.asset.durationMs ?? 0) : '--:--'}</span>
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
                  <button type="button" className={`${styles.trimHandle} ${styles.trimHandleStart}`} onPointerDown={(event) => handleTrimStartPointerDown(event, clip)} />
                  <div className={styles.clipBody}>
                    <span className={styles.clipIcon}><Film size={12} /></span>
                    <span className={styles.clipText}>{activeFile?.asset.name ?? 'Clip'}</span>
                    <span className={styles.clipDuration}>{formatTransportTime(clipDurationMs(clip))}</span>
                  </div>
                  <button type="button" className={`${styles.trimHandle} ${styles.trimHandleEnd}`} onPointerDown={(event) => handleTrimEndPointerDown(event, clip)} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export const Timeline = TimelinePanel;
