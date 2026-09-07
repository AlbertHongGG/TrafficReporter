/**
 * Playback clock (Blueprint §4, Phase 4-C).
 *
 * Pure per-frame step extracted from the hook's `requestAnimationFrame`
 * loop, plus an injectable frame scheduler so tests drive time with a fake
 * clock/frame port instead of real rAF.
 *
 * `advancePlaybackFrame` is a total function of its input: given the clamped
 * live playhead, the current entries, the gap anchor, a rAF timestamp, and a
 * DOM-free media sample, it returns exactly one clock decision. DOM media
 * sync (`syncVideoElement`) stays in the React glue; the `videoReady` flag
 * carries its result into the step.
 */
import { clamp, clipEndMs } from '../../domain/model';
import { getPlaybackSnapshot, getPlayheadMsFromSourceTime, hasReachedClipEnd } from './playbackPreview.usecase';
import type { GapAnchor, PlaybackSnapshot, PlaybackTimelineEntry } from './playbackTypes.usecase';

/** DOM-free view of the video element the clock step may observe. */
export interface PlaybackMediaSample {
  hasElement: boolean;
  /** Whether the glue's media sync accepted the current frame. */
  videoReady: boolean;
  readyState: number;
  seeking: boolean;
  currentTime: number;
}

export interface PlaybackFrameInput {
  livePlayheadMs: number;
  timelineDurationMs: number;
  playbackEntries: PlaybackTimelineEntry[];
  /** rAF timestamp (ms); injected so tests use a fake clock. */
  timestamp: number;
  gapAnchor: GapAnchor | null;
  media: PlaybackMediaSample;
}

export type PlaybackFrameDecision =
  /** Timeline end reached — caller must run the finish path. */
  | { kind: 'finish'; playheadMs: number }
  /** Silent gap: keep advancing from the wall-clock anchor. */
  | { kind: 'advance-gap'; nextPlayheadMs: number; gapAnchor: GapAnchor }
  /** Media not observable yet — schedule the next frame unchanged. */
  | { kind: 'wait-video' }
  /** Media-driven playhead update. */
  | {
    kind: 'drive-media';
    playheadMs: number;
    snapshot: PlaybackSnapshot;
    reachedClipEnd: boolean;
    /** Clip ended with no successor: pause the element, open a gap anchor. */
    startGap: boolean;
  };

/**
 * Single clock step. Branch order mirrors the hook's `step` callback:
 * end-check → gap fast-path → media sync gate → media-driven transport.
 */
export function advancePlaybackFrame(input: PlaybackFrameInput): PlaybackFrameDecision {
  const currentPlayheadMs = clamp(input.livePlayheadMs, 0, input.timelineDurationMs);
  if (currentPlayheadMs >= input.timelineDurationMs) {
    return { kind: 'finish', playheadMs: input.timelineDurationMs };
  }

  const snapshot = getPlaybackSnapshot(input.playbackEntries, currentPlayheadMs);
  if (!snapshot.activeVideoEntry || !snapshot.activeVideoEntry.asset.url) {
    const gapAnchor = input.gapAnchor ?? {
      originPlayheadMs: currentPlayheadMs,
      startedAt: input.timestamp,
    };
    const nextPlayheadMs = gapAnchor.originPlayheadMs + (input.timestamp - gapAnchor.startedAt);
    if (nextPlayheadMs >= input.timelineDurationMs) {
      return { kind: 'finish', playheadMs: input.timelineDurationMs };
    }
    return { kind: 'advance-gap', nextPlayheadMs, gapAnchor };
  }

  const { media } = input;
  if (
    !media.hasElement
    || !media.videoReady
    || media.readyState < 2
    || media.seeking
    || !Number.isFinite(media.currentTime)
  ) {
    return { kind: 'wait-video' };
  }

  const activeEntry = snapshot.activeVideoEntry;
  const currentClipEndMs = clipEndMs(activeEntry.clip);
  const mediaDrivenPlayheadMs = clamp(
    getPlayheadMsFromSourceTime(activeEntry, media.currentTime),
    activeEntry.clip.startMs,
    currentClipEndMs,
  );
  const reachedClipEnd = hasReachedClipEnd(currentClipEndMs, mediaDrivenPlayheadMs);
  const targetPlayheadMs = reachedClipEnd ? currentClipEndMs : mediaDrivenPlayheadMs;
  const boundedPlayheadMs = clamp(targetPlayheadMs, 0, input.timelineDurationMs);
  if (boundedPlayheadMs >= input.timelineDurationMs) {
    return { kind: 'finish', playheadMs: input.timelineDurationMs };
  }

  const nextSnapshot = getPlaybackSnapshot(input.playbackEntries, boundedPlayheadMs);
  return {
    kind: 'drive-media',
    playheadMs: boundedPlayheadMs,
    snapshot: nextSnapshot,
    reachedClipEnd,
    startGap: reachedClipEnd && !nextSnapshot.activeVideoEntry,
  };
}

/** Injectable frame port: real rAF in production, scripted in tests. */
export interface PlaybackFramePort {
  requestFrame: (callback: (timestamp: number) => void) => number;
  cancelFrame: (handle: number) => void;
}

/**
 * Drive a frame loop on an injected port. The step returns `true` to keep
 * going; `stop()` cancels the pending frame. The loop never throws: a step
 * that throws would otherwise kill the rAF chain silently.
 */
export function drivePlaybackClock(
  port: PlaybackFramePort,
  onError: (error: unknown) => void,
  step: (timestamp: number) => boolean,
): () => void {
  let handle: number | null = null;
  let stopped = false;

  const tick = (timestamp: number) => {
    if (stopped) {
      return;
    }
    handle = null;
    let keepGoing = false;
    try {
      keepGoing = step(timestamp);
    } catch (error) {
      onError(error);
      return;
    }
    if (keepGoing && !stopped) {
      handle = port.requestFrame(tick);
    }
  };

  handle = port.requestFrame(tick);
  return () => {
    stopped = true;
    if (handle !== null) {
      port.cancelFrame(handle);
      handle = null;
    }
  };
}
