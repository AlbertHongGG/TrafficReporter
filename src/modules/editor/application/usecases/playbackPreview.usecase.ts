/**
 * Playback preview state machine (Blueprint §4, Phase 4-C).
 *
 * Pure functions extracted verbatim from `../usePlaybackController.ts`:
 * active-video election, source-time mapping, preview dedup keys, and the
 * resync-threshold policy. No React, no DOM, no store — fully unit-testable.
 */
import { clipEndMs } from '../../domain/model';
import {
  CLIP_END_EPSILON_MS,
  PAUSED_SYNC_THRESHOLD_SECONDS,
  PLAYING_RESYNC_THRESHOLD_SECONDS,
} from './playbackTypes.usecase';
import type {
  PlaybackPreviewState,
  PlaybackSnapshot,
  PlaybackTimelineEntry,
} from './playbackTypes.usecase';

/**
 * Elect the active video entry for a playhead. A clip covers
 * `[startMs, endMs)`; among overlapping video clips the highest `trackOrder`
 * wins. Mirrors `getPlaybackSnapshot` in the hook.
 */
export function getPlaybackSnapshot(
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

/** Project a snapshot down to the consumer-facing preview surface. */
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

/** Map a timeline playhead to the entry's media source time (seconds). */
export function getSourceTimeSeconds(entry: PlaybackTimelineEntry, playheadMs: number): number {
  return (entry.clip.inPointMs + (playheadMs - entry.clip.startMs)) / 1000;
}

/** Map a media source time (seconds) back to the timeline playhead (ms). */
export function getPlayheadMsFromSourceTime(entry: PlaybackTimelineEntry, sourceTimeSeconds: number): number {
  return entry.clip.startMs + ((sourceTimeSeconds * 1000) - entry.clip.inPointMs);
}

/**
 * Dedup key for preview emissions. The hook suppresses `onPreviewChange`
 * while this key is unchanged (`video|placeholder` + asset id).
 */
export function buildPreviewKey(previewState: PlaybackPreviewState): string {
  return `${previewState.hasActiveVideo ? 'video' : 'placeholder'}:${previewState.previewAsset?.id ?? 'none'}`;
}

/**
 * Preview emission gate: returns the next key and whether the consumer must
 * be notified. Pure form of the hook's `emitPreviewState` dedup.
 */
export function shouldEmitPreviewState(lastKey: string, previewState: PlaybackPreviewState): {
  nextKey: string;
  emit: boolean;
} {
  const nextKey = buildPreviewKey(previewState);
  if (lastKey === nextKey) {
    return { nextKey: lastKey, emit: false };
  }
  return { nextKey, emit: true };
}

export interface SyncDriftPolicy {
  playing: boolean;
  forceSeek: boolean;
  clipChanged: boolean;
}

/**
 * Max tolerated drift (seconds) before a hard media seek. Mirrors the hook's
 * `maxDriftSeconds` selection: forced seeks and clip switches snap (`0`),
 * playing tolerates `0.75s`, paused tolerates `0.04s`.
 */
export function resolveSyncDriftThresholdSeconds(policy: SyncDriftPolicy): number {
  if (policy.forceSeek || policy.clipChanged) {
    return 0;
  }
  return policy.playing ? PLAYING_RESYNC_THRESHOLD_SECONDS : PAUSED_SYNC_THRESHOLD_SECONDS;
}

/** True when a media-driven playhead has effectively reached the clip end. */
export function hasReachedClipEnd(clipEndMsValue: number, mediaDrivenPlayheadMs: number, epsilonMs = CLIP_END_EPSILON_MS): boolean {
  return mediaDrivenPlayheadMs >= clipEndMsValue - epsilonMs;
}
