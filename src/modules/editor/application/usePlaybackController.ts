/**
 * Playback controller — React glue (Blueprint §4, Phase 4-D).
 *
 * Slim surface: subscribes to controller props via `latestStateRef`, owns
 * the `<video>` element sync (`syncVideoElement` + pending paused seeks +
 * media-event listeners), and forwards transport decisions to the playback
 * service (`createPlaybackService`). The service owns gap anchors, the live
 * playhead, preview dedup, store commits, and the clock step; this hook
 * feeds it the production ports (default wall clock + rAF, store writers,
 * ref-forwarded transport callbacks) and applies the resolved
 * `SyncVideoOptions` to the element after each service call.
 */
import React, { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { createPlaybackService, type PlaybackService } from './usecases/playbackService.usecase';
import { defaultPlaybackPorts, type PlaybackPorts } from './usecases/playbackPorts.usecase';
import {
  getPlaybackSnapshot,
  getSourceTimeSeconds,
} from './usecases/playbackPreview.usecase';
import {
  PAUSED_SYNC_THRESHOLD_SECONDS,
  PLAYING_RESYNC_THRESHOLD_SECONDS,
  type PlaybackPreviewState,
  type PlaybackTimelineEntry,
  type SyncVideoOptions,
} from './usecases/playbackTypes.usecase';
import type { LiveTransportSnapshot } from './liveTransport';
import type { PlaybackMediaSample } from './usecases/playbackClock.usecase';

// Compatibility surface: consumers (`useEditorPlayback`, `VideoPlayerPanel`)
// keep importing these from the hook module.
export type { PlaybackPreviewState, PlaybackTimelineEntry, SyncVideoOptions };
export { getPlaybackPreviewState } from './usecases/playbackPreview.usecase';

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

interface UsePlaybackControllerArgs {
  isPlaying: boolean;
  playheadMs: number;
  timelineDurationMs: number;
  previewVolume: number;
  previewMuted: boolean;
  playbackEntries: PlaybackTimelineEntry[];
  videoRef: React.RefObject<HTMLVideoElement | null>;
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
  onTransportUpdate,
  onPreviewChange,
}: UsePlaybackControllerArgs) {
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

  const pendingPausedVideoSeekRef = useRef<{
    clipId: string;
    assetUrl: string;
    expectedTime: number;
  } | null>(null);

  const serviceRef = useRef<PlaybackService | null>(null);
  if (serviceRef.current === null) {
    const basePorts = defaultPlaybackPorts();
    const ports: PlaybackPorts = {
      ...basePorts,
      getState: () => {
        const current = latestStateRef.current;
        return {
          isPlaying: current.isPlaying,
          playheadMs: current.playheadMs,
          timelineDurationMs: current.timelineDurationMs,
          previewVolume: current.previewVolume,
          previewMuted: current.previewMuted,
          playbackEntries: current.playbackEntries,
        };
      },
      transport: {
        onTransportUpdate: (transport) => {
          latestStateRef.current.onTransportUpdate?.(transport);
        },
        onPreviewChange: (previewState) => {
          latestStateRef.current.onPreviewChange?.(previewState);
        },
      },
    };
    serviceRef.current = createPlaybackService(ports, playheadMs);
  }

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
    [flushPendingPausedVideoSeek, videoRef],
  );

  const syncDomToService = useCallback((syncOptions: SyncVideoOptions) => {
    const service = serviceRef.current;
    if (!service) {
      return;
    }
    const current = latestStateRef.current;
    const livePlayheadMs = service.getLivePlayheadMs();
    const snapshot = getPlaybackSnapshot(current.playbackEntries, livePlayheadMs);
    syncVideoElement(snapshot.activeVideoEntry, livePlayheadMs, syncOptions);
  }, [syncVideoElement]);

  const togglePlay = useCallback(() => {
    const service = serviceRef.current;
    if (!service) {
      return;
    }
    const result = service.togglePlay();
    if (!result.ok || result.value.kind === 'noop-empty-timeline') {
      return;
    }
    const current = latestStateRef.current;
    if (result.value.kind === 'stopped') {
      syncDomToService({
        playing: false,
        previewMuted: current.previewMuted,
        previewVolume: current.previewVolume,
      });
      return;
    }
    syncDomToService({
      playing: true,
      previewMuted: current.previewMuted,
      previewVolume: current.previewVolume,
      forceSeek: true,
    });
  }, [syncDomToService]);

  const seekTo = useCallback((nextPlayheadMs: number, preservePlayback = false, commit = true) => {
    const service = serviceRef.current;
    if (!service) {
      return;
    }
    const result = service.seekTo(nextPlayheadMs, preservePlayback, commit);
    if (!result.ok) {
      return;
    }
    const current = latestStateRef.current;
    syncDomToService({
      playing: result.value.continuePlayback,
      previewMuted: current.previewMuted,
      previewVolume: current.previewVolume,
      forceSeek: true,
      scrubbing: !commit && !result.value.continuePlayback,
    });
  }, [syncDomToService]);

  const seekBy = useCallback((deltaMs: number) => {
    const service = serviceRef.current;
    if (!service) {
      return;
    }
    const result = service.seekBy(deltaMs);
    if (!result.ok) {
      return;
    }
    const outcome = result.value;
    // `seekBy` routes through `seekTo`, so the only `kind`-carrying outcome
    // is the empty-timeline no-op; anything else is a `SeekOutcome`.
    if ('kind' in outcome) {
      return;
    }
    const current = latestStateRef.current;
    syncDomToService({
      playing: outcome.continuePlayback,
      previewMuted: current.previewMuted,
      previewVolume: current.previewVolume,
      forceSeek: true,
      scrubbing: false,
    });
  }, [syncDomToService]);

  const stopPlayback = useCallback(() => {
    const service = serviceRef.current;
    if (!service) {
      return;
    }
    const result = service.stopPlayback();
    if (!result.ok) {
      return;
    }
    const current = latestStateRef.current;
    syncDomToService({
      playing: false,
      previewMuted: current.previewMuted,
      previewVolume: current.previewVolume,
    });
  }, [syncDomToService]);

  useEffect(() => {
    if (!isPlaying) {
      return undefined;
    }

    let frameId = 0;

    const step = (timestamp: number) => {
      const service = serviceRef.current;
      if (!service) {
        frameId = requestAnimationFrame(step);
        return;
      }
      const current = latestStateRef.current;
      const livePlayheadMs = service.getLivePlayheadMs();
      const snapshot = getPlaybackSnapshot(current.playbackEntries, livePlayheadMs);
      if (!snapshot.activeVideoEntry || !snapshot.activeVideoEntry.asset.url) {
        const driven = service.stepClock(timestamp, {
          hasElement: videoRef.current !== null,
          videoReady: false,
          readyState: 0,
          seeking: false,
          currentTime: Number.NaN,
        });
        if (driven === null && service.getLivePlayheadMs() >= current.timelineDurationMs) {
          const finished = latestStateRef.current;
          const finishedSnapshot = getPlaybackSnapshot(finished.playbackEntries, service.getLivePlayheadMs());
          syncVideoElement(finishedSnapshot.activeVideoEntry, service.getLivePlayheadMs(), {
            playing: false,
            previewMuted: finished.previewMuted,
            previewVolume: finished.previewVolume,
          });
        }
        frameId = requestAnimationFrame(step);
        return;
      }

      const videoReady = syncVideoElement(
        snapshot.activeVideoEntry,
        livePlayheadMs,
        {
          playing: true,
          previewMuted: current.previewMuted,
          previewVolume: current.previewVolume,
        },
      );

      const element = videoRef.current;
      const media: PlaybackMediaSample = element
        ? {
          hasElement: true,
          videoReady,
          readyState: element.readyState,
          seeking: element.seeking,
          currentTime: element.currentTime,
        }
        : {
          hasElement: false,
          videoReady,
          readyState: 0,
          seeking: false,
          currentTime: Number.NaN,
        };
      const driven = service.stepClock(timestamp, media);
      if (driven && !driven.activeVideoEntry) {
        videoRef.current?.pause();
      }
      frameId = requestAnimationFrame(step);
    };

    frameId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frameId);
  }, [isPlaying, syncVideoElement, videoRef]);

  useEffect(() => {
    if (isPlaying) {
      return;
    }

    const service = serviceRef.current;
    if (!service) {
      return;
    }
    const { syncOptions } = service.syncPausedTransport(playheadMs);
    syncDomToService(syncOptions);
  }, [isPlaying, playheadMs, playbackEntries, previewMuted, previewVolume, syncDomToService]);

  useEffect(() => {
    if (!isPlaying) {
      return;
    }

    const service = serviceRef.current;
    if (!service) {
      return;
    }
    const { syncOptions } = service.refreshPlayingTransport();
    syncDomToService(syncOptions);
  }, [isPlaying, playbackEntries, previewMuted, previewVolume, syncDomToService]);

  return {
    togglePlay,
    seekTo,
    seekBy,
    stopPlayback,
  };
}
