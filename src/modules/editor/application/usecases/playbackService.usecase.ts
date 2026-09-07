/**
 * Playback service orchestrator (Blueprint §4, Phase 4-C).
 *
 * Stateful glue between the pure decisions (`playbackControls`,
 * `playbackPreview`, `playbackClock`) and the injectable outside world
 * (`playbackPorts`). Observable behavior mirrors
 * `../usePlaybackController.ts` one-to-one:
 *
 * - `togglePlay` / `seekTo` / `seekBy` / `stopPlayback` commit the store
 *   under the same `>= 1ms` guards and maintain the same gap-anchor rules.
 * - `emitTransportState` clamps, publishes a live-transport snapshot, and
 *   dedups preview emissions by key.
 * - `stepClock` reproduces the rAF `step` branches; `startClock` drives it
 *   on the injected frame port (fake clock in tests).
 *
 * DOM media sync (`syncVideoElement`) stays in the React hook until Wave 2:
 * `syncTransport` returns the resolved `SyncVideoOptions` so the slimmed
 * hook can feed its existing element sync unchanged.
 */
import {
  buildLiveTransportSnapshot,
  resolveLiveTransportMode,
} from '../liveTransport';
import { getPlaybackSnapshot } from './playbackPreview.usecase';
import {
  decideFinishPlayback,
  decideSeekBy,
  decideSeekTo,
  decideTogglePlay,
} from './playbackControls.usecase';
import { advancePlaybackFrame, drivePlaybackClock } from './playbackClock.usecase';
import type { LiveTransportMode } from '../liveTransport';
import type { PlaybackMediaSample } from './playbackClock.usecase';
import type {
  GapAnchor,
  PlaybackControlResult,
  PlaybackControllerState,
  PlaybackSnapshot,
  PlaybackTransportEmission,
  SyncVideoOptions,
} from './playbackTypes.usecase';
import type { PlaybackPorts } from './playbackPorts.usecase';
import { playbackErr, playbackOk } from './playbackTypes.usecase';
import { shouldEmitPreviewState } from './playbackPreview.usecase';

export interface PlaybackSyncResult {
  emission: PlaybackTransportEmission;
  syncOptions: SyncVideoOptions;
}

export type TogglePlayOutcome =
  | { kind: 'noop-empty-timeline' }
  | { kind: 'stopped'; boundedPlayheadMs: number }
  | { kind: 'started'; originPlayheadMs: number; committedPlayhead: boolean };

export interface SeekOutcome {
  boundedPlayheadMs: number;
  continuePlayback: boolean;
  committedPlayhead: boolean;
  stoppedPlaying: boolean;
}

export interface FinishOutcome {
  boundedPlayheadMs: number;
  committedPlayhead: boolean;
  stoppedPlaying: boolean;
}

export interface PlaybackService {
  getLivePlayheadMs: () => number;
  emitTransportState: (targetPlayheadMs: number, mode: LiveTransportMode) => PlaybackTransportEmission;
  syncTransport: (
    targetPlayheadMs: number,
    options: Pick<SyncVideoOptions, 'playing'> & Partial<Pick<SyncVideoOptions, 'forceSeek' | 'scrubbing'>>,
  ) => PlaybackSyncResult;
  togglePlay: () => PlaybackControlResult<TogglePlayOutcome>;
  seekTo: (nextPlayheadMs: number, preservePlayback?: boolean, commit?: boolean) => PlaybackControlResult<SeekOutcome>;
  seekBy: (deltaMs: number) => PlaybackControlResult<SeekOutcome | TogglePlayOutcome>;
  stopPlayback: () => PlaybackControlResult<FinishOutcome>;
  finishPlayback: (finalPlayheadMs?: number) => PlaybackControlResult<FinishOutcome>;
  /** Mirror of the hook's paused effect: re-anchor paused transport. */
  syncPausedTransport: (playheadMs: number) => PlaybackSyncResult;
  /** Mirror of the hook's playing effect: refresh transport on entry edits. */
  refreshPlayingTransport: () => PlaybackSyncResult;
  /** One clock tick with an injected media sample; `null` keeps the loop. */
  stepClock: (timestamp: number, media: PlaybackMediaSample) => PlaybackSnapshot | null;
  /** Drive `stepClock` on the injected frame port until `stop()` or finish. */
  startClock: (getMedia: () => PlaybackMediaSample) => () => void;
}

export function createPlaybackService(ports: PlaybackPorts, initialLivePlayheadMs = 0): PlaybackService {
  let livePlayheadMs = initialLivePlayheadMs;
  let gapAnchor: GapAnchor | null = null;
  let lastPreviewKey = '';

  const readState = (): PlaybackControllerState => ports.getState();

  const emitTransportState = (targetPlayheadMs: number, mode: LiveTransportMode): PlaybackTransportEmission => {
    const state = readState();
    const boundedPlayheadMs = Math.min(state.timelineDurationMs, Math.max(0, targetPlayheadMs));
    const snapshot = getPlaybackSnapshot(state.playbackEntries, boundedPlayheadMs);
    livePlayheadMs = boundedPlayheadMs;

    const transport = buildLiveTransportSnapshot(boundedPlayheadMs, mode);
    ports.transport.onTransportUpdate?.(transport);

    const gate = shouldEmitPreviewState(lastPreviewKey, {
      previewAsset: snapshot.previewAsset,
      hasActiveVideo: snapshot.hasActiveVideo,
    });
    lastPreviewKey = gate.nextKey;
    if (gate.emit) {
      ports.transport.onPreviewChange?.({
        previewAsset: snapshot.previewAsset,
        hasActiveVideo: snapshot.hasActiveVideo,
      });
    }
    return { boundedPlayheadMs, snapshot, transport };
  };

  const syncTransport = (
    targetPlayheadMs: number,
    options: Pick<SyncVideoOptions, 'playing'> & Partial<Pick<SyncVideoOptions, 'forceSeek' | 'scrubbing'>>,
  ): PlaybackSyncResult => {
    const state = readState();
    const syncOptions: SyncVideoOptions = {
      playing: options.playing,
      previewMuted: state.previewMuted,
      previewVolume: state.previewVolume,
      forceSeek: options.forceSeek ?? false,
      scrubbing: options.scrubbing ?? false,
    };
    const emission = emitTransportState(
      targetPlayheadMs,
      resolveLiveTransportMode(syncOptions.playing, syncOptions.scrubbing),
    );
    return { emission, syncOptions };
  };

  const finishPlayback = (finalPlayheadMs?: number): PlaybackControlResult<FinishOutcome> => {
    const state = readState();
    const decision = decideFinishPlayback({
      finalPlayheadMs: finalPlayheadMs ?? null,
      livePlayheadMs,
      currentPlayheadMs: state.playheadMs,
      currentlyPlaying: state.isPlaying,
      timelineDurationMs: state.timelineDurationMs,
    });
    if (!decision.ok) {
      return decision;
    }
    gapAnchor = null;
    syncTransport(decision.value.boundedPlayheadMs, { playing: false });
    if (decision.value.commitPlayhead) {
      ports.store.setPlayhead(decision.value.boundedPlayheadMs);
    }
    if (decision.value.stopPlaying) {
      ports.store.setPlaying(false);
    }
    return playbackOk({
      boundedPlayheadMs: decision.value.boundedPlayheadMs,
      committedPlayhead: decision.value.commitPlayhead,
      stoppedPlaying: decision.value.stopPlaying,
    });
  };

  const stopPlayback = (): PlaybackControlResult<FinishOutcome> => finishPlayback(livePlayheadMs);

  const seekTo = (
    nextPlayheadMs: number,
    preservePlayback = false,
    commit = true,
  ): PlaybackControlResult<SeekOutcome> => {
    const state = readState();
    const boundedTarget = Math.min(state.timelineDurationMs, Math.max(0, nextPlayheadMs));
    if (!Number.isFinite(nextPlayheadMs)) {
      return playbackErr('non-finite-playhead');
    }
    const targetSnapshot = getPlaybackSnapshot(state.playbackEntries, boundedTarget);
    const decision = decideSeekTo({
      nextPlayheadMs,
      preservePlayback,
      commit,
      currentlyPlaying: state.isPlaying,
      currentPlayheadMs: state.playheadMs,
      timelineDurationMs: state.timelineDurationMs,
      hasActiveVideoEntry: targetSnapshot.activeVideoEntry !== null,
      nowMs: ports.clock.now(),
    });
    if (!decision.ok) {
      return decision;
    }
    const intent = decision.value;
    syncTransport(intent.boundedPlayheadMs, {
      playing: intent.continuePlayback,
      forceSeek: intent.forceSeek,
      scrubbing: intent.scrubbing,
    });
    if (intent.commitPlayhead) {
      ports.store.setPlayhead(intent.boundedPlayheadMs);
    }
    if (intent.continuePlayback) {
      gapAnchor = intent.gapAnchor;
    } else {
      gapAnchor = null;
      if (intent.stopPlaying) {
        ports.store.setPlaying(false);
      }
    }
    return playbackOk({
      boundedPlayheadMs: intent.boundedPlayheadMs,
      continuePlayback: intent.continuePlayback,
      committedPlayhead: intent.commitPlayhead,
      stoppedPlaying: !intent.continuePlayback && intent.stopPlaying,
    });
  };

  const seekBy = (deltaMs: number): PlaybackControlResult<SeekOutcome | TogglePlayOutcome> => {
    const state = readState();
    const decision = decideSeekBy({
      deltaMs,
      livePlayheadMs,
      currentlyPlaying: state.isPlaying,
      timelineDurationMs: state.timelineDurationMs,
    });
    if (!decision.ok) {
      return decision;
    }
    if (decision.value.kind === 'noop-empty-timeline') {
      return playbackOk({ kind: 'noop-empty-timeline' } as const);
    }
    return seekTo(decision.value.targetPlayheadMs, decision.value.preservePlayback, true);
  };

  const togglePlay = (): PlaybackControlResult<TogglePlayOutcome> => {
    const state = readState();
    const decision = decideTogglePlay({
      currentlyPlaying: state.isPlaying,
      currentPlayheadMs: state.playheadMs,
      livePlayheadMs,
      timelineDurationMs: state.timelineDurationMs,
    });
    if (!decision.ok) {
      return decision;
    }
    if (decision.value.kind === 'noop-empty-timeline') {
      return playbackOk({ kind: 'noop-empty-timeline' } as const);
    }
    if (decision.value.kind === 'stop') {
      const stopped = stopPlayback();
      if (!stopped.ok) {
        return stopped;
      }
      return playbackOk({ kind: 'stopped', boundedPlayheadMs: stopped.value.boundedPlayheadMs } as const);
    }
    const origin = decision.value.originPlayheadMs;
    const { emission } = syncTransport(origin, { playing: true, forceSeek: true });
    if (decision.value.commitPlayhead) {
      ports.store.setPlayhead(origin);
    }
    gapAnchor = emission.snapshot.activeVideoEntry
      ? null
      : { originPlayheadMs: origin, startedAt: ports.clock.now() };
    ports.store.setPlaying(true);
    return playbackOk({
      kind: 'started',
      originPlayheadMs: origin,
      committedPlayhead: decision.value.commitPlayhead,
    } as const);
  };

  const syncPausedTransport = (playheadMs: number): PlaybackSyncResult => {
    gapAnchor = null;
    return syncTransport(playheadMs, { playing: false, forceSeek: false });
  };

  const refreshPlayingTransport = (): PlaybackSyncResult => syncTransport(livePlayheadMs, {
    playing: true,
    forceSeek: false,
  });

  const stepClock = (timestamp: number, media: PlaybackMediaSample): PlaybackSnapshot | null => {
    const state = readState();
    const frame = advancePlaybackFrame({
      livePlayheadMs,
      timelineDurationMs: state.timelineDurationMs,
      playbackEntries: state.playbackEntries,
      timestamp,
      gapAnchor,
      media,
    });
    if (frame.kind === 'finish') {
      void finishPlayback(frame.playheadMs);
      return null;
    }
    if (frame.kind === 'advance-gap') {
      gapAnchor = frame.gapAnchor;
      emitTransportState(frame.nextPlayheadMs, 'playing');
      return null;
    }
    if (frame.kind === 'wait-video') {
      return null;
    }
    gapAnchor = null;
    emitTransportState(frame.playheadMs, 'playing');
    if (frame.startGap) {
      gapAnchor = { originPlayheadMs: frame.playheadMs, startedAt: timestamp };
    }
    return frame.snapshot;
  };

  const startClock = (getMedia: () => PlaybackMediaSample): (() => void) => drivePlaybackClock(
    ports.frames,
    ports.onClockError,
    (timestamp) => {
      const state = readState();
      if (!state.isPlaying) {
        return false;
      }
      const frame = advancePlaybackFrame({
        livePlayheadMs,
        timelineDurationMs: state.timelineDurationMs,
        playbackEntries: state.playbackEntries,
        timestamp,
        gapAnchor,
        media: getMedia(),
      });
      if (frame.kind === 'finish') {
        void finishPlayback(frame.playheadMs);
        return false;
      }
      if (frame.kind === 'advance-gap') {
        gapAnchor = frame.gapAnchor;
        emitTransportState(frame.nextPlayheadMs, 'playing');
        return true;
      }
      if (frame.kind === 'wait-video') {
        return true;
      }
      gapAnchor = null;
      emitTransportState(frame.playheadMs, 'playing');
      if (frame.startGap) {
        gapAnchor = { originPlayheadMs: frame.playheadMs, startedAt: timestamp };
      }
      return true;
    },
  );

  return {
    getLivePlayheadMs: () => livePlayheadMs,
    emitTransportState,
    syncTransport,
    togglePlay,
    seekTo,
    seekBy,
    stopPlayback,
    finishPlayback,
    syncPausedTransport,
    refreshPlayingTransport,
    stepClock,
    startClock,
  };
}
