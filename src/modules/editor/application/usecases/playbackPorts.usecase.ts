/**
 * Playback use-case ports (Blueprint §4, Phase 4-C).
 *
 * The seam between pure playback use-cases and the outside world. Every
 * playback service reads controller state, writes the store, emits
 * transport/preview updates, and schedules frames exclusively through this
 * interface, so tests inject fake ports while production uses
 * {@link defaultPlaybackPorts} (real clock + rAF + `useEditorStore`).
 *
 * This file is the ONLY place in `usecases/playback*` allowed to touch the
 * store, the wall clock, or rAF. Use-case files must never import
 * `bindings.commands` nor subscribe to React state.
 */
import { getActiveFile, getTimelineDuration } from '../../domain/model';
import { useEditorStore } from '../store/store';
import type { LiveTransportSnapshot } from '../liveTransport';
import type {
  PlaybackControllerState,
  PlaybackPreviewState,
  PlaybackTimelineEntry,
} from './playbackTypes.usecase';
import type { PlaybackFramePort } from './playbackClock.usecase';

/** Wall-clock source (ms); fake in tests. */
export interface PlaybackClockPort {
  now: () => number;
}

/** Store writes a playback service may perform (structural subset). */
export interface PlaybackStoreWriter {
  setPlayhead: (playheadMs: number) => void;
  setPlaying: (isPlaying: boolean) => void;
}

/** Transport/preview emissions forwarded to the React glue. */
export interface PlaybackTransportPorts {
  onTransportUpdate?: (transport: LiveTransportSnapshot) => void;
  onPreviewChange?: (previewState: PlaybackPreviewState) => void;
}

/** Full injectable environment for the playback service. */
export interface PlaybackPorts {
  /** Read the latest controller inputs (hook props in production). */
  getState: () => PlaybackControllerState;
  /** Persist playhead / playing flag. */
  store: PlaybackStoreWriter;
  /** Forward transport + preview emissions. */
  transport: PlaybackTransportPorts;
  /** Wall clock for gap anchors. */
  clock: PlaybackClockPort;
  /** Frame scheduler for the playback loop. */
  frames: PlaybackFramePort;
  /** Sink for clock-step failures (loop never throws). */
  onClockError: (error: unknown) => void;
}

/** Build controller state from the active store file (production default). */
export function readPlaybackControllerState(): PlaybackControllerState {
  const workspace = useEditorStore.getState().workspace;
  const activeFile = getActiveFile(workspace);
  if (!activeFile) {
    return {
      isPlaying: false,
      playheadMs: 0,
      timelineDurationMs: 0,
      previewVolume: 0.85,
      previewMuted: false,
      playbackEntries: [],
    };
  }
  const playbackEntries: PlaybackTimelineEntry[] = activeFile.asset.url
    ? activeFile.clips.map((clip) => ({
      clip,
      asset: activeFile.asset,
      trackOrder: activeFile.track.order,
    }))
    : [];
  return {
    isPlaying: activeFile.isPlaying,
    playheadMs: activeFile.playheadMs,
    timelineDurationMs: getTimelineDuration(activeFile.clips),
    previewVolume: activeFile.previewVolume,
    previewMuted: activeFile.previewMuted,
    playbackEntries,
  };
}

/** Production ports: real clock + rAF + `useEditorStore` writes. */
export function defaultPlaybackPorts(transport: PlaybackTransportPorts = {}): PlaybackPorts {
  return {
    getState: readPlaybackControllerState,
    store: {
      setPlayhead: (playheadMs) => {
        useEditorStore.getState().setPlayhead(playheadMs);
      },
      setPlaying: (isPlaying) => {
        useEditorStore.getState().setPlaying(isPlaying);
      },
    },
    transport,
    clock: {
      now: () => performance.now(),
    },
    frames: {
      requestFrame: (callback) => requestAnimationFrame(callback),
      cancelFrame: (handle) => {
        cancelAnimationFrame(handle);
      },
    },
    onClockError: () => undefined,
  };
}
