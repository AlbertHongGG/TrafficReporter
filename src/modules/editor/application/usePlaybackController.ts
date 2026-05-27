import React, { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import type { EditorAsset, TimelineClip } from '../domain/model';
import { clamp, clipEndMs } from '../domain/model';
import type { EditorAction } from './editorReducer';
import {
  buildLiveTransportSnapshot,
  resolveLiveTransportMode,
  type LiveTransportSnapshot,
} from './liveTransport';

const PLAYING_RESYNC_THRESHOLD_SECONDS = 0.75;
const PAUSED_SYNC_THRESHOLD_SECONDS = 0.04;
const CLIP_END_EPSILON_MS = 18;

function syncMediaTime(element: HTMLMediaElement, expectedTime: number, maxDriftSeconds: number) {
  try {
    if (Math.abs(element.currentTime - expectedTime) > maxDriftSeconds) {
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
}

interface SyncVideoOptions {
  playing: boolean;
  previewMuted: boolean;
  previewVolume: number;
  forceSeek?: boolean;
  scrubbing?: boolean;
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
  let activeVideoEntry: PlaybackTimelineEntry | null = null;

  for (const entry of playbackEntries) {
    if (playheadMs < entry.clip.startMs || playheadMs >= clipEndMs(entry.clip)) {
      continue;
    }

    if (entry.asset.hasVideo && (!activeVideoEntry || entry.trackOrder > activeVideoEntry.trackOrder)) {
      activeVideoEntry = entry;
    }
  }

  return {
    activeVideoEntry,
    previewAsset: activeVideoEntry?.asset ?? null,
    hasActiveVideo: Boolean(activeVideoEntry?.asset.url),
  };
}

function getSourceTimeSeconds(entry: PlaybackTimelineEntry, playheadMs: number) {
  return (entry.clip.inPointMs + (playheadMs - entry.clip.startMs)) / 1000;
}

function getPlayheadMsFromSourceTime(entry: PlaybackTimelineEntry, sourceTimeSeconds: number) {
  return entry.clip.startMs + ((sourceTimeSeconds * 1000) - entry.clip.inPointMs);
}

interface UsePlaybackControllerArgs {
  isPlaying: boolean;
  playheadMs: number;
  timelineDurationMs: number;
  previewVolume: number;
  previewMuted: boolean;
  playbackEntries: PlaybackTimelineEntry[];
  videoRef: React.RefObject<HTMLVideoElement | null>;
  dispatch: React.Dispatch<EditorAction>;
  onTransportUpdate?: (transport: LiveTransportSnapshot) => void;
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
  dispatch,
  onTransportUpdate,
  onPreviewChange,
}: UsePlaybackControllerArgs) {
  const gapAnchorRef = useRef<{ originPlayheadMs: number; startedAt: number } | null>(null);
  const livePlayheadMsRef = useRef(playheadMs);
  const lastPreviewKeyRef = useRef<string>('');
  const pendingPausedVideoSeekRef = useRef<{
    clipId: string;
    assetUrl: string;
    expectedTime: number;
  } | null>(null);
  const latestStateRef = useRef({
    isPlaying,
    playheadMs,
    timelineDurationMs,
    previewVolume,
    previewMuted,
    playbackEntries,
    onTransportUpdate,
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
      onTransportUpdate,
      onPreviewChange,
    };
  }, [isPlaying, onPreviewChange, onTransportUpdate, playbackEntries, playheadMs, previewMuted, previewVolume, timelineDurationMs]);

  const emitPreviewState = useCallback((previewState: PlaybackPreviewState) => {
    const { onPreviewChange: handlePreviewChange } = latestStateRef.current;
    const nextKey = `${previewState.hasActiveVideo ? 'video' : 'placeholder'}:${previewState.previewAsset?.id ?? 'none'}`;
    if (lastPreviewKeyRef.current === nextKey) {
      return;
    }

    lastPreviewKeyRef.current = nextKey;
    handlePreviewChange?.(previewState);
  }, []);

  const flushPendingPausedVideoSeek = useCallback(() => {
    const element = videoRef.current;
    const pendingSeek = pendingPausedVideoSeekRef.current;
    if (!element || !pendingSeek) {
      return;
    }

    if (element.dataset.clipId !== pendingSeek.clipId || element.dataset.assetUrl !== pendingSeek.assetUrl) {
      pendingPausedVideoSeekRef.current = null;
      return;
    }

    if (element.readyState < HTMLMediaElement.HAVE_METADATA || element.seeking) {
      return;
    }

    pendingPausedVideoSeekRef.current = null;
    syncMediaTime(element, pendingSeek.expectedTime, 0);
  }, [videoRef]);

  useEffect(() => {
    const element = videoRef.current;
    if (!element) {
      return undefined;
    }

    const handleSeekSettled = () => {
      flushPendingPausedVideoSeek();
    };

    element.addEventListener('loadedmetadata', handleSeekSettled);
    element.addEventListener('canplay', handleSeekSettled);
    element.addEventListener('seeked', handleSeekSettled);

    return () => {
      element.removeEventListener('loadedmetadata', handleSeekSettled);
      element.removeEventListener('canplay', handleSeekSettled);
      element.removeEventListener('seeked', handleSeekSettled);
    };
  }, [flushPendingPausedVideoSeek, videoRef]);

  const syncVideoElement = useCallback(
    (
      activeVideoEntry: PlaybackTimelineEntry | null,
      targetPlayheadMs: number,
      {
        playing,
        previewMuted: isPreviewMuted,
        previewVolume: currentPreviewVolume,
        forceSeek = false,
        scrubbing = false,
      }: SyncVideoOptions,
    ) => {
      const element = videoRef.current;
      if (!element) {
        return false;
      }

      if (!activeVideoEntry || !activeVideoEntry.asset.url) {
        pendingPausedVideoSeekRef.current = null;
        element.pause();
        element.muted = true;
        element.volume = 0;
        delete element.dataset.clipId;
        delete element.dataset.assetUrl;
        element.removeAttribute('src');
        element.load();
        return true;
      }

      const expectedTime = getSourceTimeSeconds(activeVideoEntry, targetPlayheadMs);
      const shouldMute = isPreviewMuted || activeVideoEntry.clip.muted || !activeVideoEntry.asset.hasAudio;
      element.muted = shouldMute;
      element.volume = shouldMute ? 0 : currentPreviewVolume;
      const clipChanged = element.dataset.clipId !== activeVideoEntry.clip.id;
      const sourceChanged = element.dataset.assetUrl !== activeVideoEntry.asset.url;
      element.dataset.clipId = activeVideoEntry.clip.id;

      if (sourceChanged) {
        pendingPausedVideoSeekRef.current = null;
        element.dataset.assetUrl = activeVideoEntry.asset.url;
        element.src = activeVideoEntry.asset.url;
        element.load();

        const syncWhenReady = () => {
          if (element.dataset.assetUrl !== activeVideoEntry.asset.url) {
            return;
          }

          element.muted = shouldMute;
          element.volume = shouldMute ? 0 : currentPreviewVolume;
          if (!playing) {
            pendingPausedVideoSeekRef.current = {
              clipId: activeVideoEntry.clip.id,
              assetUrl: activeVideoEntry.asset.url,
              expectedTime,
            };
            flushPendingPausedVideoSeek();
            element.pause();
            return;
          }

          syncMediaTime(element, expectedTime, 0);
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
        return false;
      }

      if (!playing && scrubbing) {
        pendingPausedVideoSeekRef.current = {
          clipId: activeVideoEntry.clip.id,
          assetUrl: activeVideoEntry.asset.url,
          expectedTime,
        };
        flushPendingPausedVideoSeek();
        element.pause();
        return true;
      }

      pendingPausedVideoSeekRef.current = null;

      const maxDriftSeconds = forceSeek || clipChanged
        ? 0
        : playing
          ? PLAYING_RESYNC_THRESHOLD_SECONDS
          : PAUSED_SYNC_THRESHOLD_SECONDS;
      syncMediaTime(element, expectedTime, maxDriftSeconds);

      if (playing) {
        if (element.paused) {
          void element.play().catch(() => {
            /* ignore transient play rejections */
          });
        }
        return true;
      }

      element.pause();
      return true;
    },
    [videoRef],
  );

  const emitTransportState = React.useEffectEvent((targetPlayheadMs: number, transportMode: LiveTransportSnapshot['mode']) => {
    const {
      timelineDurationMs: currentTimelineDurationMs,
      playbackEntries: currentPlaybackEntries,
      onTransportUpdate: handleTransportUpdate,
    } = latestStateRef.current;
    const boundedPlayheadMs = clamp(targetPlayheadMs, 0, currentTimelineDurationMs);
    const snapshot = getPlaybackSnapshot(currentPlaybackEntries, boundedPlayheadMs);

    livePlayheadMsRef.current = boundedPlayheadMs;
    handleTransportUpdate?.(buildLiveTransportSnapshot(boundedPlayheadMs, transportMode));
    emitPreviewState({
      previewAsset: snapshot.previewAsset,
      hasActiveVideo: snapshot.hasActiveVideo,
    });
    return {
      boundedPlayheadMs,
      snapshot,
    };
  });

  const syncTransport = React.useEffectEvent((targetPlayheadMs: number, options: SyncVideoOptions) => {
    const {
      previewMuted: isPreviewMuted,
      previewVolume: currentPreviewVolume,
    } = latestStateRef.current;
    const nextOptions = {
      ...options,
      previewMuted: isPreviewMuted,
      previewVolume: currentPreviewVolume,
    } satisfies SyncVideoOptions;
    const result = emitTransportState(
      targetPlayheadMs,
      resolveLiveTransportMode(nextOptions.playing, nextOptions.scrubbing),
    );
    syncVideoElement(
      result.snapshot.activeVideoEntry,
      result.boundedPlayheadMs,
      nextOptions,
    );
    return result;
  });

  const finishPlayback = (finalPlayheadMs: number) => {
    const { playheadMs: currentPlayheadMs, timelineDurationMs: currentTimelineDurationMs, isPlaying: currentlyPlaying } = latestStateRef.current;
    const committedPlayheadMs = clamp(livePlayheadMsRef.current, 0, currentTimelineDurationMs);
    const boundedPlayheadMs = clamp(finalPlayheadMs ?? committedPlayheadMs, 0, currentTimelineDurationMs);
    gapAnchorRef.current = null;
    syncTransport(boundedPlayheadMs, {
      playing: false,
      previewMuted: true,
      previewVolume: 0,
    });

    if (Math.abs(currentPlayheadMs - boundedPlayheadMs) >= 1) {
      dispatch({ type: 'set-playhead', playheadMs: boundedPlayheadMs });
    }

    if (currentlyPlaying) {
      dispatch({ type: 'set-playing', isPlaying: false });
    }

    return boundedPlayheadMs;
  };

  const stopPlayback = () => {
    const { timelineDurationMs: currentTimelineDurationMs } = latestStateRef.current;
    finishPlayback(clamp(livePlayheadMsRef.current, 0, currentTimelineDurationMs));
  };

  const seekTo = (nextPlayheadMs: number, preservePlayback = false, commit = true) => {
    const {
      isPlaying: currentlyPlaying,
      playheadMs: currentPlayheadMs,
      timelineDurationMs: currentTimelineDurationMs,
    } = latestStateRef.current;
    const boundedPlayheadMs = clamp(nextPlayheadMs, 0, currentTimelineDurationMs);
    const continuePlayback = preservePlayback && currentlyPlaying;
    const result = syncTransport(boundedPlayheadMs, {
      playing: continuePlayback,
      previewMuted: true,
      previewVolume: 0,
      forceSeek: true,
      scrubbing: !commit && !continuePlayback,
    });

    if (commit && Math.abs(currentPlayheadMs - boundedPlayheadMs) >= 1) {
      dispatch({ type: 'set-playhead', playheadMs: boundedPlayheadMs });
    }

    if (continuePlayback) {
      gapAnchorRef.current = result.snapshot.activeVideoEntry
        ? null
        : {
            originPlayheadMs: boundedPlayheadMs,
            startedAt: performance.now(),
          };
      return;
    }

    gapAnchorRef.current = null;
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
    const result = syncTransport(originPlayheadMs, {
      playing: true,
      previewMuted: true,
      previewVolume: 0,
      forceSeek: true,
    });

    if (Math.abs(originPlayheadMs - currentPlayheadMs) >= 1) {
      dispatch({ type: 'set-playhead', playheadMs: originPlayheadMs });
    }

    gapAnchorRef.current = result.snapshot.activeVideoEntry
      ? null
      : {
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
    if (!isPlaying) {
      return undefined;
    }

    let frameId = 0;

    const step = (timestamp: number) => {
      const {
        timelineDurationMs: currentTimelineDurationMs,
        playbackEntries: currentPlaybackEntries,
        previewMuted: isPreviewMuted,
        previewVolume: currentPreviewVolume,
      } = latestStateRef.current;
      const currentPlayheadMs = clamp(livePlayheadMsRef.current, 0, currentTimelineDurationMs);
      if (currentPlayheadMs >= currentTimelineDurationMs) {
        finishPlayback(currentTimelineDurationMs);
        return;
      }

      const snapshot = getPlaybackSnapshot(currentPlaybackEntries, currentPlayheadMs);
      if (!snapshot.activeVideoEntry || !snapshot.activeVideoEntry.asset.url) {
        const gapAnchor = gapAnchorRef.current ?? {
          originPlayheadMs: currentPlayheadMs,
          startedAt: timestamp,
        };
        gapAnchorRef.current = gapAnchor;

        const nextPlayheadMs = gapAnchor.originPlayheadMs + (timestamp - gapAnchor.startedAt);
        if (nextPlayheadMs >= currentTimelineDurationMs) {
          finishPlayback(currentTimelineDurationMs);
          return;
        }

        emitTransportState(nextPlayheadMs, 'playing');
        frameId = requestAnimationFrame(step);
        return;
      }

      gapAnchorRef.current = null;

      const element = videoRef.current;
      const videoReady = syncVideoElement(
        snapshot.activeVideoEntry,
        currentPlayheadMs,
        {
          playing: true,
          previewMuted: isPreviewMuted,
          previewVolume: currentPreviewVolume,
        },
      );

      if (!element || !videoReady || element.readyState < 2 || element.seeking || !Number.isFinite(element.currentTime)) {
        frameId = requestAnimationFrame(step);
        return;
      }

      const currentClipEndMs = clipEndMs(snapshot.activeVideoEntry.clip);
      const mediaDrivenPlayheadMs = clamp(
        getPlayheadMsFromSourceTime(snapshot.activeVideoEntry, element.currentTime),
        snapshot.activeVideoEntry.clip.startMs,
        currentClipEndMs,
      );
      const reachedClipEnd = mediaDrivenPlayheadMs >= currentClipEndMs - CLIP_END_EPSILON_MS;
      const nextTransport = emitTransportState(reachedClipEnd ? currentClipEndMs : mediaDrivenPlayheadMs, 'playing');

      if (nextTransport.boundedPlayheadMs >= currentTimelineDurationMs) {
        finishPlayback(currentTimelineDurationMs);
        return;
      }

      if (reachedClipEnd && !nextTransport.snapshot.activeVideoEntry) {
        element.pause();
        gapAnchorRef.current = {
          originPlayheadMs: nextTransport.boundedPlayheadMs,
          startedAt: timestamp,
        };
      }

      frameId = requestAnimationFrame(step);
    };

    frameId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frameId);
  }, [finishPlayback, isPlaying, syncVideoElement, videoRef]);

  useEffect(() => {
    if (isPlaying) {
      return;
    }

    gapAnchorRef.current = null;
    syncTransport(playheadMs, {
      playing: false,
      previewMuted: true,
      previewVolume: 0,
      forceSeek: false,
    });
  }, [isPlaying, playheadMs, playbackEntries, previewMuted, previewVolume]);

  useEffect(() => {
    if (!isPlaying) {
      return;
    }

    syncTransport(livePlayheadMsRef.current, {
      playing: true,
      previewMuted: true,
      previewVolume: 0,
      forceSeek: false,
    });
  }, [isPlaying, playbackEntries, previewMuted, previewVolume]);

  return {
    togglePlay,
    seekTo,
    seekBy,
    stopPlayback,
  };
}