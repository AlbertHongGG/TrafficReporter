/**
 * Playback control decisions (Blueprint §4, Phase 4-C).
 *
 * Pure, store-free decision functions for toggle / seek / seekBy / stop /
 * finish, extracted from `../usePlaybackController.ts`. Each mirrors the
 * hook's branching one-to-one (clamp bounds, `>= 1ms` commit guards,
 * gap-anchor handling, empty-timeline no-ops) and reports invalid inputs as
 * {@link PlaybackControlResult} errors instead of throwing, so error paths
 * are unit-testable.
 *
 * Callers (the `playbackService` orchestrator, and in Wave 2 the slimmed
 * hook) apply the returned intents through injectable store ports.
 */
import { clamp } from '../../domain/model';
import { playbackErr, playbackOk } from './playbackTypes.usecase';
import type { GapAnchor, PlaybackControlResult } from './playbackTypes.usecase';

/** Validate a caller-supplied playhead: must be finite (bounds come later). */
export function validatePlayheadInput(nextPlayheadMs: number): PlaybackControlResult<number> {
  if (!Number.isFinite(nextPlayheadMs)) {
    return playbackErr('non-finite-playhead');
  }
  return playbackOk(nextPlayheadMs);
}

/** Validate the timeline duration: finite and non-negative. */
export function validateDurationInput(timelineDurationMs: number): PlaybackControlResult<number> {
  if (!Number.isFinite(timelineDurationMs) || timelineDurationMs < 0) {
    return playbackErr('invalid-duration');
  }
  return playbackOk(timelineDurationMs);
}

/** Clamp a playhead into `[0, duration]`, mirroring every hook call-site. */
export function clampPlayhead(playheadMs: number, timelineDurationMs: number): number {
  return clamp(playheadMs, 0, timelineDurationMs);
}

/**
 * True when the hook would commit a playhead to the store
 * (`Math.abs(current - bounded) >= 1`).
 */
export function shouldCommitPlayhead(currentPlayheadMs: number, boundedPlayheadMs: number, epsilonMs = 1): boolean {
  return Math.abs(currentPlayheadMs - boundedPlayheadMs) >= epsilonMs;
}

export interface TogglePlayInput {
  currentlyPlaying: boolean;
  currentPlayheadMs: number;
  livePlayheadMs: number;
  timelineDurationMs: number;
}

export type TogglePlayDecision =
  | { kind: 'noop-empty-timeline' }
  | { kind: 'stop' }
  | { kind: 'start'; originPlayheadMs: number; commitPlayhead: boolean };

/**
 * Decide what `togglePlay` must do. Start restarts from `0` when the live
 * playhead already reached the end; stop delegates to `finishPlayback`.
 */
export function decideTogglePlay(input: TogglePlayInput): PlaybackControlResult<TogglePlayDecision> {
  const duration = validateDurationInput(input.timelineDurationMs);
  if (!duration.ok) {
    return duration;
  }
  if (duration.value === 0) {
    return playbackOk({ kind: 'noop-empty-timeline' } as const);
  }
  if (input.currentlyPlaying) {
    return playbackOk({ kind: 'stop' } as const);
  }
  const originPlayheadMs = input.livePlayheadMs >= duration.value ? 0 : input.livePlayheadMs;
  return playbackOk({
    kind: 'start',
    originPlayheadMs,
    commitPlayhead: shouldCommitPlayhead(input.currentPlayheadMs, originPlayheadMs),
  } as const);
}

export interface SeekToInput {
  nextPlayheadMs: number;
  preservePlayback: boolean;
  commit: boolean;
  currentlyPlaying: boolean;
  currentPlayheadMs: number;
  timelineDurationMs: number;
  /** Whether the bounded target has an active video entry (drives anchors). */
  hasActiveVideoEntry: boolean;
  /** Wall-clock now (ms) for gap-anchor creation; injected for tests. */
  nowMs: number;
}

export interface SeekToDecision {
  boundedPlayheadMs: number;
  continuePlayback: boolean;
  forceSeek: boolean;
  scrubbing: boolean;
  commitPlayhead: boolean;
  gapAnchor: GapAnchor | null;
  /** Paused-seek while playing stops playback (hook's trailing branch). */
  stopPlaying: boolean;
}

/** Decide the full `seekTo` intent, including transport flags and anchors. */
export function decideSeekTo(input: SeekToInput): PlaybackControlResult<SeekToDecision> {
  const target = validatePlayheadInput(input.nextPlayheadMs);
  if (!target.ok) {
    return target;
  }
  const duration = validateDurationInput(input.timelineDurationMs);
  if (!duration.ok) {
    return duration;
  }
  const boundedPlayheadMs = clampPlayhead(target.value, duration.value);
  const continuePlayback = input.preservePlayback && input.currentlyPlaying;

  if (continuePlayback) {
    return playbackOk({
      boundedPlayheadMs,
      continuePlayback,
      forceSeek: true,
      scrubbing: false,
      commitPlayhead: input.commit && shouldCommitPlayhead(input.currentPlayheadMs, boundedPlayheadMs),
      gapAnchor: input.hasActiveVideoEntry
        ? null
        : { originPlayheadMs: boundedPlayheadMs, startedAt: input.nowMs },
      stopPlaying: false,
    });
  }

  return playbackOk({
    boundedPlayheadMs,
    continuePlayback,
    forceSeek: true,
    scrubbing: !input.commit,
    commitPlayhead: input.commit && shouldCommitPlayhead(input.currentPlayheadMs, boundedPlayheadMs),
    gapAnchor: null,
    stopPlaying: input.currentlyPlaying,
  });
}

export interface SeekByInput {
  deltaMs: number;
  livePlayheadMs: number;
  currentlyPlaying: boolean;
  timelineDurationMs: number;
}

export type SeekByDecision =
  | { kind: 'noop-empty-timeline' }
  | { kind: 'seek'; targetPlayheadMs: number; preservePlayback: boolean };

/**
 * Decide the `seekBy` target. An empty timeline is a silent no-op (hook
 * parity); the caller routes `seek` through `decideSeekTo` with
 * `preservePlayback = currentlyPlaying, commit = true`.
 */
export function decideSeekBy(input: SeekByInput): PlaybackControlResult<SeekByDecision> {
  if (!Number.isFinite(input.deltaMs)) {
    return playbackErr('non-finite-delta');
  }
  const duration = validateDurationInput(input.timelineDurationMs);
  if (!duration.ok) {
    return duration;
  }
  if (duration.value === 0) {
    return playbackOk({ kind: 'noop-empty-timeline' } as const);
  }
  if (!Number.isFinite(input.livePlayheadMs)) {
    return playbackErr('non-finite-playhead');
  }
  return playbackOk({
    kind: 'seek',
    targetPlayheadMs: input.livePlayheadMs + input.deltaMs,
    preservePlayback: input.currentlyPlaying,
  } as const);
}

export interface FinishPlaybackInput {
  /** Explicit final playhead; `null`/`undefined` falls back to the live one. */
  finalPlayheadMs: number | null | undefined;
  livePlayheadMs: number;
  currentPlayheadMs: number;
  currentlyPlaying: boolean;
  timelineDurationMs: number;
}

export interface FinishPlaybackDecision {
  boundedPlayheadMs: number;
  commitPlayhead: boolean;
  stopPlaying: boolean;
}

/** Decide the `finishPlayback` intent (also backs `stopPlayback`). */
export function decideFinishPlayback(input: FinishPlaybackInput): PlaybackControlResult<FinishPlaybackDecision> {
  const duration = validateDurationInput(input.timelineDurationMs);
  if (!duration.ok) {
    return duration;
  }
  const committedPlayheadMs = clampPlayhead(input.livePlayheadMs, duration.value);
  const rawFinal = input.finalPlayheadMs ?? committedPlayheadMs;
  if (!Number.isFinite(rawFinal)) {
    return playbackErr('non-finite-playhead');
  }
  const boundedPlayheadMs = clampPlayhead(rawFinal, duration.value);
  return playbackOk({
    boundedPlayheadMs,
    commitPlayhead: shouldCommitPlayhead(input.currentPlayheadMs, boundedPlayheadMs),
    stopPlaying: input.currentlyPlaying,
  });
}
