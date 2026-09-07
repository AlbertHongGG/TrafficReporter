import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { EditorFileState, TimelineClip } from '../../../modules/editor/domain/model';
import { formatRulerLabel } from '../../../modules/editor/domain/model';
import {
  getPlaybackPreviewState,
  usePlaybackController,
  type PlaybackPreviewState,
  type PlaybackTimelineEntry,
} from '../../../modules/editor/application/usePlaybackController';
import {
  buildLiveTransportSnapshot,
  createLiveTransportStore,
  type LiveTransportSnapshot,
} from '../../../modules/editor/application/liveTransport';
import { emitPlateWindowLiveTransport } from '../../../modules/editor/infrastructure/plateWindowApi';
import { useVideoViewport } from '../video-player/useVideoViewport';

export interface UseEditorPlaybackOptions {
  activeFile: EditorFileState | null | undefined;
  activeClips: TimelineClip[];
  timelineDurationMs: number;
  isScrubbing: boolean;
  isActive?: boolean;
  plateWindowLiveSyncEnabledRef: React.MutableRefObject<boolean>;
}

export function useEditorPlayback({
  activeFile,
  activeClips,
  timelineDurationMs,
  isScrubbing,
  isActive = true,
  plateWindowLiveSyncEnabledRef,
}: UseEditorPlaybackOptions) {
  const [livePreviewState, setLivePreviewState] = useState<PlaybackPreviewState>({
    previewAsset: null,
    hasActiveVideo: false,
  });

  const previewContainerRef = useRef<HTMLDivElement>(null);
  const previewVideoRef = useRef<HTMLVideoElement>(null);
  const currentTimecodeRef = useRef<HTMLSpanElement>(null);
  const livePlayheadMsRef = useRef(0);
  const liveTransportStore = useMemo(() => createLiveTransportStore(), []);

  const currentPlayheadMs = activeFile?.playheadMs ?? 0;
  const currentPreviewVolume = activeFile?.previewVolume ?? 0.85;
  const currentPreviewMuted = activeFile?.previewMuted ?? false;
  const currentIsPlaying = activeFile?.isPlaying ?? false;

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
  const previewState = currentIsPlaying || isScrubbing ? livePreviewState : committedPreviewState;

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
  }, [liveTransportStore, plateWindowLiveSyncEnabledRef]);

  const handleTransportUpdate = useCallback((transport: LiveTransportSnapshot) => {
    applyLiveTransportUpdate(transport, true);
  }, [applyLiveTransportUpdate]);

  const handlePreviewChange = useCallback((nextPreviewState: PlaybackPreviewState) => {
    setLivePreviewState((currentPreviewState) => {
      if (
        currentPreviewState.previewAsset === nextPreviewState.previewAsset &&
        currentPreviewState.hasActiveVideo === nextPreviewState.hasActiveVideo
      ) {
        return currentPreviewState;
      }
      return nextPreviewState;
    });
  }, []);

  const { togglePlay, seekTo, seekBy, stopPlayback } = usePlaybackController({
    isPlaying: currentIsPlaying,
    playheadMs: currentPlayheadMs,
    timelineDurationMs,
    previewVolume: currentPreviewVolume,
    previewMuted: currentPreviewMuted,
    playbackEntries,
    videoRef: previewVideoRef,
    onTransportUpdate: handleTransportUpdate,
    onPreviewChange: handlePreviewChange,
  });

  const { previewViewport } = useVideoViewport(
    previewContainerRef,
    previewVideoRef,
    activeFile?.asset.width,
    activeFile?.asset.height,
    activeFile?.id,
    previewState.previewAsset?.id,
  );

  // Synchronize paused transport
  useEffect(() => {
    if (currentIsPlaying || isScrubbing) {
      return;
    }
    applyLiveTransportUpdate(
      buildLiveTransportSnapshot(currentPlayheadMs, 'paused'),
      false,
    );
  }, [activeFile?.id, applyLiveTransportUpdate, currentIsPlaying, currentPlayheadMs, isScrubbing]);

  // Stop playback when deactivated
  useEffect(() => {
    if (!isActive && currentIsPlaying) {
      stopPlayback();
    }
  }, [currentIsPlaying, isActive, stopPlayback]);

  return {
    previewContainerRef,
    previewVideoRef,
    currentTimecodeRef,
    livePlayheadMsRef,
    liveTransportStore,
    previewState,
    previewViewport,
    currentPlayheadMs,
    currentIsPlaying,
    togglePlay,
    seekTo,
    seekBy,
    stopPlayback,
  };
}
