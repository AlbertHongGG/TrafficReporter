/**
 * Playback use-case shared types (Blueprint §4, Phase 4-C).
 *
 * Canonical use-case-side definitions extracted from
 * `../usePlaybackController.ts` (Wave 1: additive only — the hook and its
 * consumers are untouched; Wave 2 re-points the hook glue at these
 * definitions). Every numeric threshold below copies the hook verbatim so
 * behavior stays identical.
 *
 * `PlaybackPreviewState` intentionally mirrors the hook's exported interface
 * (also referenced by `VideoPlayerPanel.tsx` via the hook today); Wave 2
 * will re-export this definition from the hook for compatibility.
 */
import type { EditorAsset, TimelineClip } from '../../domain/model';
import type { LiveTransportSnapshot } from '../liveTransport';

/** Drift beyond which a playing video element is hard-resynced (seconds). */
export const PLAYING_RESYNC_THRESHOLD_SECONDS = 0.75;

/** Drift beyond which a paused video element is hard-resynced (seconds). */
export const PAUSED_SYNC_THRESHOLD_SECONDS = 0.04;

/** Media-driven playhead within this distance of a clip end counts as ended. */
export const CLIP_END_EPSILON_MS = 18;

/**
 * Store commits are skipped when the playhead moves less than this, mirroring
 * the hook's `Math.abs(current - bounded) >= 1` guards.
 */
export const PLAYHEAD_COMMIT_EPSILON_MS = 1;

/** One timeline entry considered for preview transport. */
export interface PlaybackTimelineEntry {
  clip: TimelineClip;
  asset: EditorAsset;
  trackOrder: number;
}

/** Minimal preview surface consumed by `VideoPlayerPanel`. */
export interface PlaybackPreviewState {
  previewAsset: EditorAsset | null;
  hasActiveVideo: boolean;
}

/** Preview state plus the winning video entry behind it. */
export interface PlaybackSnapshot extends PlaybackPreviewState {
  activeVideoEntry: PlaybackTimelineEntry | null;
}

/** Options describing how the video element should follow the playhead. */
export interface SyncVideoOptions {
  playing: boolean;
  previewMuted: boolean;
  previewVolume: number;
  forceSeek?: boolean;
  scrubbing?: boolean;
}

/**
 * Observable controller inputs. The React hook feeds these from props every
 * render; the use-case service reads them through an injectable getter so
 * tests can supply fakes while production binds the store (see
 * `playbackPorts.usecase.ts`).
 */
export interface PlaybackControllerState {
  isPlaying: boolean;
  playheadMs: number;
  timelineDurationMs: number;
  previewVolume: number;
  previewMuted: boolean;
  playbackEntries: PlaybackTimelineEntry[];
}

/** Wall-clock anchor used to advance the playhead across silent gaps. */
export interface GapAnchor {
  originPlayheadMs: number;
  startedAt: number;
}

/** Transport emission produced alongside every playhead update. */
export interface PlaybackTransportEmission {
  boundedPlayheadMs: number;
  snapshot: PlaybackSnapshot;
  transport: LiveTransportSnapshot;
}

/** Machine-readable reasons a playback control request can be rejected. */
export type PlaybackControlErrorReason =
  | 'empty-timeline'
  | 'non-finite-playhead'
  | 'non-finite-delta'
  | 'invalid-duration';

/** Discriminated result for fallible playback control decisions. */
export type PlaybackControlResult<T> =
  | { ok: true; value: T }
  | { ok: false; reason: PlaybackControlErrorReason };

export function playbackOk<T>(value: T): PlaybackControlResult<T> {
  return { ok: true, value };
}

export function playbackErr<T>(reason: PlaybackControlErrorReason): PlaybackControlResult<T> {
  return { ok: false, reason };
}
