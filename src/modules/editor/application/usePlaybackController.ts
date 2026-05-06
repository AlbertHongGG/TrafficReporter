import React, { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import type { EditorAsset, TimelineClip } from '../domain/model';
import { clamp, clipEndMs } from '../domain/model';
import type { EditorAction } from './editorReducer';

const PLAYING_SYNC_THRESHOLD_SECONDS = 0.18;
const PAUSED_SYNC_THRESHOLD_SECONDS = 0.04;

function syncMediaTime(element: HTMLMediaElement, expectedTime: number, isPlaying: boolean) {
  try {
    const threshold = isPlaying ? PLAYING_SYNC_THRESHOLD_SECONDS : PAUSED_SYNC_THRESHOLD_SECONDS;
    if (Math.abs(element.currentTime - expectedTime) > threshold) {
      element.currentTime = expectedTime;
    }
    return true;
  } catch {
    return false;
  }
}

export interface PlaybackTimelineEntry {
  clip: TimelineClip;
  asset: EditorAsset;
  trackOrder: number;
}

export interface PlaybackPreviewState {
  previewAsset: EditorAsset | null;
  hasActiveVideo: boolean;
}

interface PlaybackSnapshot extends PlaybackPreviewState {
  activeVideoEntry: PlaybackTimelineEntry | null;
  activeAudioEntries: PlaybackTimelineEntry[];
}

export function getPlaybackPreviewState(
  playbackEntries: PlaybackTimelineEntry[],
  playheadMs: number,
): PlaybackPreviewState {
  const snapshot = getPlaybackSnapshot(playbackEntries, playheadMs);
  return {
    previewAsset: snapshot.previewAsset,
    hasActiveVideo: snapshot.hasActiveVideo,
  };
}

function getPlaybackSnapshot(
  playbackEntries: PlaybackTimelineEntry[],
  playheadMs: number,
): PlaybackSnapshot {
  const activeAudioEntries: PlaybackTimelineEntry[] = [];
  let activeVideoEntry: PlaybackTimelineEntry | null = null;

  for (const entry of playbackEntries) {
    if (playheadMs < entry.clip.startMs || playheadMs >= clipEndMs(entry.clip)) {
      continue;
    }

    if (entry.asset.hasAudio && !entry.clip.muted) {
      activeAudioEntries.push(entry);
    }

    if (entry.asset.hasVideo && (!activeVideoEntry || entry.trackOrder > activeVideoEntry.trackOrder)) {
      activeVideoEntry = entry;
    }
  }

  return {
    activeVideoEntry,
    activeAudioEntries,
    previewAsset: activeVideoEntry?.asset ?? activeAudioEntries[0]?.asset ?? null,
    hasActiveVideo: Boolean(activeVideoEntry?.asset.url),
  };
}

interface UsePlaybackControllerArgs {
  isPlaying: boolean;
  playheadMs: number;
  timelineDurationMs: number;
  previewVolume: number;
  previewMuted: boolean;
  playbackEntries: PlaybackTimelineEntry[];
  videoRef: React.RefObject<HTMLVideoElement | null>;
  audioRefs: React.RefObject<Map<string, HTMLAudioElement>>;
  dispatch: React.Dispatch<EditorAction>;
  onTransportFrame?: (playheadMs: number) => void;
  onPreviewChange?: (previewState: PlaybackPreviewState) => void;
}

export function usePlaybackController({
  isPlaying,
  playheadMs,
  timelineDurationMs,
  previewVolume,
  previewMuted,
  playbackEntries,
  videoRef,
  audioRefs,
  dispatch,
  onTransportFrame,
  onPreviewChange,
}: UsePlaybackControllerArgs) {
  const anchorRef = useRef<{ originPlayheadMs: number; startedAt: number } | null>(null);
  const livePlayheadMsRef = useRef(playheadMs);
  const lastPreviewKeyRef = useRef<string>('');
  const latestStateRef = useRef({
    isPlaying,
    playheadMs,
    timelineDurationMs,
    previewVolume,
    previewMuted,
    playbackEntries,
    onTransportFrame,
    onPreviewChange,
  });

  useLayoutEffect(() => {
    latestStateRef.current = {
      isPlaying,
      playheadMs,
      timelineDurationMs,
      previewVolume,
      previewMuted,
      playbackEntries,
      onTransportFrame,
      onPreviewChange,
    };
  }, [isPlaying, onPreviewChange, onTransportFrame, playbackEntries, playheadMs, previewMuted, previewVolume, timelineDurationMs]);

  const emitPreviewState = useCallback((previewState: PlaybackPreviewState) => {
    const { onPreviewChange: handlePreviewChange } = latestStateRef.current;
    const nextKey = `${previewState.hasActiveVideo ? 'video' : 'placeholder'}:${previewState.previewAsset?.id ?? 'none'}`;
    if (lastPreviewKeyRef.current === nextKey) {
      return;
    }

    lastPreviewKeyRef.current = nextKey;
    handlePreviewChange?.(previewState);
  }, []);

  const syncVideoElement = useCallback(
    (activeVideoEntry: PlaybackTimelineEntry | null, targetPlayheadMs: number, playing: boolean) => {
      const element = videoRef.current;
      if (!element) {
        return;
      }

      if (!activeVideoEntry || !activeVideoEntry.asset.url) {
        element.pause();
        delete element.dataset.clipId;
        delete element.dataset.assetUrl;
        element.removeAttribute('src');
        element.load();
        return;
      }

      const expectedTime = (activeVideoEntry.clip.inPointMs + (targetPlayheadMs - activeVideoEntry.clip.startMs)) / 1000;
      const sourceChanged = element.dataset.clipId !== activeVideoEntry.clip.id
        || element.dataset.assetUrl !== activeVideoEntry.asset.url;

      if (sourceChanged) {
        element.dataset.clipId = activeVideoEntry.clip.id;
        element.dataset.assetUrl = activeVideoEntry.asset.url;
        element.src = activeVideoEntry.asset.url;
        element.load();

        const syncWhenReady = () => {
          if (element.dataset.clipId !== activeVideoEntry.clip.id) {
            return;
          }

          syncMediaTime(element, expectedTime, false);
          if (playing) {
            void element.play().catch(() => {
              /* ignore transient video startup failures while the source is warming up */
            });
            return;
          }

          element.pause();
        };

        element.addEventListener('loadedmetadata', syncWhenReady, { once: true });
        element.addEventListener('canplay', syncWhenReady, { once: true });
        return;
      }

      syncMediaTime(element, expectedTime, playing);

      if (playing) {
        if (element.paused) {
          void element.play().catch(() => {
            /* ignore transient play rejections */
          });
        }
        return;
      }

      element.pause();
    },
    [videoRef],
  );

  const syncTransport = React.useEffectEvent((targetPlayheadMs: number, playing: boolean) => {
    const {
      timelineDurationMs: currentTimelineDurationMs,
      playbackEntries: currentPlaybackEntries,
      onTransportFrame: handleTransportFrame,
      previewMuted: isPreviewMuted,
      previewVolume: currentPreviewVolume,
    } = latestStateRef.current;
    const boundedPlayheadMs = clamp(targetPlayheadMs, 0, currentTimelineDurationMs);
    const snapshot = getPlaybackSnapshot(currentPlaybackEntries, boundedPlayheadMs);
    const activeAudioIds = new Set(snapshot.activeAudioEntries.map((entry) => entry.clip.id));

    livePlayheadMsRef.current = boundedPlayheadMs;
    handleTransportFrame?.(boundedPlayheadMs);
    emitPreviewState({
      previewAsset: snapshot.previewAsset,
      hasActiveVideo: snapshot.hasActiveVideo,
    });
    syncVideoElement(snapshot.activeVideoEntry, boundedPlayheadMs, playing);

    for (const [clipId, element] of audioRefs.current.entries()) {
      if (!activeAudioIds.has(clipId)) {
        element.pause();
      }
    }

    for (const entry of snapshot.activeAudioEntries) {
      const element = audioRefs.current.get(entry.clip.id);
      if (!element || !entry.asset.url) {
        continue;
      }

      const expectedTime = (entry.clip.inPointMs + (boundedPlayheadMs - entry.clip.startMs)) / 1000;
      element.muted = isPreviewMuted;
      element.volume = isPreviewMuted ? 0 : currentPreviewVolume;

      syncMediaTime(element, expectedTime, playing);

      if (playing) {
        if (element.paused) {
          void element.play().catch(() => {
            /* ignore individual audio element failures */
          });
        }
        continue;
      }

      element.pause();
    }
  });

  const stopPlayback = () => {
    const { playheadMs: currentPlayheadMs, timelineDurationMs: currentTimelineDurationMs, isPlaying: currentlyPlaying } = latestStateRef.current;
    const committedPlayheadMs = clamp(livePlayheadMsRef.current, 0, currentTimelineDurationMs);
    anchorRef.current = null;
    syncTransport(committedPlayheadMs, false);

    if (Math.abs(currentPlayheadMs - committedPlayheadMs) >= 1) {
      dispatch({ type: 'set-playhead', playheadMs: committedPlayheadMs });
    }

    if (currentlyPlaying) {
      dispatch({ type: 'set-playing', isPlaying: false });
    }
  };

  const seekTo = (nextPlayheadMs: number, preservePlayback = false) => {
    const {
      isPlaying: currentlyPlaying,
      playheadMs: currentPlayheadMs,
      timelineDurationMs: currentTimelineDurationMs,
    } = latestStateRef.current;
    const boundedPlayheadMs = clamp(nextPlayheadMs, 0, currentTimelineDurationMs);
    syncTransport(boundedPlayheadMs, preservePlayback && currentlyPlaying);

    if (Math.abs(currentPlayheadMs - boundedPlayheadMs) >= 1) {
      dispatch({ type: 'set-playhead', playheadMs: boundedPlayheadMs });
    }

    if (preservePlayback && currentlyPlaying) {
      anchorRef.current = {
        originPlayheadMs: boundedPlayheadMs,
        startedAt: performance.now(),
      };
      return;
    }

    anchorRef.current = null;
    if (currentlyPlaying) {
      dispatch({ type: 'set-playing', isPlaying: false });
    }
  };

  const togglePlay = () => {
    const {
      isPlaying: currentlyPlaying,
      playheadMs: currentPlayheadMs,
      timelineDurationMs: currentTimelineDurationMs,
    } = latestStateRef.current;

    if (currentTimelineDurationMs === 0) {
      return;
    }

    if (currentlyPlaying) {
      stopPlayback();
      return;
    }

    const originPlayheadMs = livePlayheadMsRef.current >= currentTimelineDurationMs ? 0 : livePlayheadMsRef.current;
    syncTransport(originPlayheadMs, true);

    if (Math.abs(originPlayheadMs - currentPlayheadMs) >= 1) {
      dispatch({ type: 'set-playhead', playheadMs: originPlayheadMs });
    }

    anchorRef.current = {
      originPlayheadMs,
      startedAt: performance.now(),
    };

    if (!currentlyPlaying) {
      dispatch({ type: 'set-playing', isPlaying: true });
    }
  };

  const seekBy = (deltaMs: number) => {
    const { isPlaying: currentlyPlaying, timelineDurationMs: currentTimelineDurationMs } = latestStateRef.current;
    if (currentTimelineDurationMs === 0) {
      return;
    }

    seekTo(livePlayheadMsRef.current + deltaMs, currentlyPlaying);
  };

  useEffect(() => {
    if (!isPlaying || !anchorRef.current) {
      return undefined;
    }

    let frameId = 0;

    const step = (timestamp: number) => {
      const anchor = anchorRef.current;
      if (!anchor) {
        return;
      }

      const elapsedMs = timestamp - anchor.startedAt;
      const nextPlayheadMs = anchor.originPlayheadMs + elapsedMs;
      if (nextPlayheadMs >= timelineDurationMs) {
        livePlayheadMsRef.current = timelineDurationMs;
        anchorRef.current = null;
        syncTransport(timelineDurationMs, false);
        if (Math.abs(playheadMs - timelineDurationMs) >= 1) {
          dispatch({ type: 'set-playhead', playheadMs: timelineDurationMs });
        }
        dispatch({ type: 'set-playing', isPlaying: false });
        return;
      }

      syncTransport(nextPlayheadMs, true);

      frameId = requestAnimationFrame(step);
    };

    frameId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frameId);
  }, [dispatch, isPlaying, playheadMs, timelineDurationMs]);

  useEffect(() => {
    if (isPlaying) {
      return;
    }

    syncTransport(playheadMs, false);
  }, [isPlaying, playheadMs, playbackEntries, previewMuted, previewVolume]);

  useEffect(() => {
    if (!isPlaying) {
      return;
    }

    syncTransport(livePlayheadMsRef.current, true);
  }, [isPlaying, playbackEntries, previewMuted, previewVolume]);

  return {
    togglePlay,
    seekTo,
    seekBy,
    stopPlayback,
  };
}