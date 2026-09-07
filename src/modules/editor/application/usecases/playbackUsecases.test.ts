/**
 * Playback use-cases coverage (Blueprint §4, Phase 4-C).
 *
 * Covers preview state transitions, seek boundaries, control decisions, the
 * frame clock, and the service orchestrator — all with a fake clock and
 * fake ports (no DOM, no store, no timers).
 */
import { describe, expect, it } from 'vitest';
import type { LiveTransportSnapshot } from '../liveTransport';
import type { EditorAsset, TimelineClip } from '../../domain/model';
import {
  buildPreviewKey,
  getPlaybackPreviewState,
  getPlaybackSnapshot,
  getPlayheadMsFromSourceTime,
  getSourceTimeSeconds,
  hasReachedClipEnd,
  resolveSyncDriftThresholdSeconds,
  shouldEmitPreviewState,
} from './playbackPreview.usecase';
import {
  clampPlayhead,
  decideFinishPlayback,
  decideSeekBy,
  decideSeekTo,
  decideTogglePlay,
  shouldCommitPlayhead,
} from './playbackControls.usecase';
import { advancePlaybackFrame, drivePlaybackClock } from './playbackClock.usecase';
import type { PlaybackMediaSample } from './playbackClock.usecase';
import { createPlaybackService } from './playbackService.usecase';
import type {
  GapAnchor,
  PlaybackControllerState,
  PlaybackPreviewState,
  PlaybackTimelineEntry,
} from './playbackTypes.usecase';
import type { PlaybackPorts } from './playbackPorts.usecase';

function makeAsset(overrides: Partial<EditorAsset> = {}): EditorAsset {
  return {
    id: 'a1',
    name: 'clip.mp4',
    path: '/tmp/clip.mp4',
    url: 'file:///tmp/clip.mp4',
    thumbnailUrl: null,
    hasVideo: true,
    hasAudio: true,
    durationMs: 10000,
    fps: 30,
    audioBitrateKbps: 128,
    width: 1920,
    height: 1080,
    kind: 'video',
    ...overrides,
  };
}

function makeClip(overrides: Partial<TimelineClip> = {}): TimelineClip {
  return {
    id: 'c1',
    assetId: 'a1',
    trackId: 't1',
    startMs: 0,
    inPointMs: 0,
    outPointMs: 5000,
    muted: false,
    ...overrides,
  };
}

function makeEntry(
  clip: TimelineClip = makeClip(),
  asset: EditorAsset = makeAsset(),
  trackOrder = 1,
): PlaybackTimelineEntry {
  return { clip, asset, trackOrder };
}

function makeState(overrides: Partial<PlaybackControllerState> = {}): PlaybackControllerState {
  return {
    isPlaying: false,
    playheadMs: 0,
    timelineDurationMs: 8000,
    previewVolume: 0.85,
    previewMuted: false,
    playbackEntries: [makeEntry()],
    ...overrides,
  };
}

function readyMedia(overrides: Partial<PlaybackMediaSample> = {}): PlaybackMediaSample {
  return {
    hasElement: true,
    videoReady: true,
    readyState: 4,
    seeking: false,
    currentTime: 1,
    ...overrides,
  };
}

interface FakePortsBundle {
  ports: PlaybackPorts;
  playheadWrites: number[];
  playingWrites: boolean[];
  transports: LiveTransportSnapshot[];
  previews: PlaybackPreviewState[];
  clockErrors: unknown[];
  frames: {
    pending: Map<number, (timestamp: number) => void>;
    cancelled: number[];
    fireAll: (timestamp: number) => void;
  };
  setNow: (nowMs: number) => void;
}

function createFakePorts(state: PlaybackControllerState): FakePortsBundle {
  const playheadWrites: number[] = [];
  const playingWrites: boolean[] = [];
  const transports: LiveTransportSnapshot[] = [];
  const previews: PlaybackPreviewState[] = [];
  const clockErrors: unknown[] = [];
  const pending = new Map<number, (timestamp: number) => void>();
  const cancelled: number[] = [];
  let nextId = 1;
  let nowMs = 1000;

  const ports: PlaybackPorts = {
    getState: () => state,
    store: {
      setPlayhead: (value) => {
        playheadWrites.push(value);
      },
      setPlaying: (value) => {
        playingWrites.push(value);
      },
    },
    transport: {
      onTransportUpdate: (transport) => {
        transports.push(transport);
      },
      onPreviewChange: (preview) => {
        previews.push(preview);
      },
    },
    clock: {
      now: () => nowMs,
    },
    frames: {
      requestFrame: (callback) => {
        const id = nextId;
        nextId += 1;
        pending.set(id, callback);
        return id;
      },
      cancelFrame: (handle) => {
        cancelled.push(handle);
        pending.delete(handle);
      },
    },
    onClockError: (error) => {
      clockErrors.push(error);
    },
  };

  return {
    ports,
    playheadWrites,
    playingWrites,
    transports,
    previews,
    clockErrors,
    frames: {
      pending,
      cancelled,
      fireAll: (timestamp) => {
        const callbacks = [...pending.values()];
        pending.clear();
        for (const callback of callbacks) {
          callback(timestamp);
        }
      },
    },
    setNow: (value) => {
      nowMs = value;
    },
  };
}

describe('playbackPreview state machine', () => {
  it('elects the highest trackOrder among overlapping video clips', () => {
    const asset = makeAsset();
    const low = makeEntry(makeClip({ id: 'low' }), asset, 1);
    const high = makeEntry(makeClip({ id: 'high' }), asset, 2);
    const snapshot = getPlaybackSnapshot([low, high], 1000);
    expect(snapshot.activeVideoEntry?.clip.id).toBe('high');
    expect(snapshot.previewAsset?.id).toBe('a1');
    expect(snapshot.hasActiveVideo).toBe(true);
  });

  it('treats clip coverage as [startMs, endMs)', () => {
    const entries = [makeEntry()];
    expect(getPlaybackSnapshot(entries, 0).activeVideoEntry).not.toBeNull();
    expect(getPlaybackSnapshot(entries, 4999).activeVideoEntry).not.toBeNull();
    expect(getPlaybackSnapshot(entries, 5000).activeVideoEntry).toBeNull();
  });

  it('ignores audio-only entries and url-less assets for hasActiveVideo', () => {
    const audioOnly = makeEntry(makeClip(), makeAsset({ hasVideo: false }));
    expect(getPlaybackPreviewState([audioOnly], 100)).toEqual({ previewAsset: null, hasActiveVideo: false });

    const urlLess = makeEntry(makeClip(), makeAsset({ url: null }));
    const preview = getPlaybackPreviewState([urlLess], 100);
    expect(preview.previewAsset?.id).toBe('a1');
    expect(preview.hasActiveVideo).toBe(false);
  });

  it('returns an empty preview when nothing covers the playhead', () => {
    expect(getPlaybackPreviewState([], 250)).toEqual({ previewAsset: null, hasActiveVideo: false });
    expect(getPlaybackSnapshot([makeEntry()], 9000).activeVideoEntry).toBeNull();
  });

  it('round-trips between timeline playhead and source time', () => {
    const entry = makeEntry(makeClip({ startMs: 1000, inPointMs: 5000 }));
    expect(getSourceTimeSeconds(entry, 2000)).toBe(6);
    expect(getPlayheadMsFromSourceTime(entry, 6)).toBe(2000);
  });

  it('dedups preview emissions by key', () => {
    const video = { previewAsset: makeAsset(), hasActiveVideo: true };
    expect(buildPreviewKey(video)).toBe('video:a1');
    expect(buildPreviewKey({ previewAsset: null, hasActiveVideo: false })).toBe('placeholder:none');

    const first = shouldEmitPreviewState('', video);
    expect(first.emit).toBe(true);
    expect(shouldEmitPreviewState(first.nextKey, video).emit).toBe(false);
    expect(shouldEmitPreviewState(first.nextKey, { previewAsset: null, hasActiveVideo: false }).emit).toBe(true);
  });

  it('resolves drift thresholds with forced seeks snapping to zero', () => {
    expect(resolveSyncDriftThresholdSeconds({ playing: true, forceSeek: true, clipChanged: false })).toBe(0);
    expect(resolveSyncDriftThresholdSeconds({ playing: true, forceSeek: false, clipChanged: true })).toBe(0);
    expect(resolveSyncDriftThresholdSeconds({ playing: true, forceSeek: false, clipChanged: false })).toBe(0.75);
    expect(resolveSyncDriftThresholdSeconds({ playing: false, forceSeek: false, clipChanged: false })).toBe(0.04);
  });

  it('detects clip-end reach within the epsilon window', () => {
    expect(hasReachedClipEnd(5000, 4982)).toBe(true);
    expect(hasReachedClipEnd(5000, 4981)).toBe(false);
  });
});

describe('playbackControls decisions', () => {
  it('togglePlay no-ops on an empty timeline', () => {
    const decision = decideTogglePlay({
      currentlyPlaying: false,
      currentPlayheadMs: 0,
      livePlayheadMs: 0,
      timelineDurationMs: 0,
    });
    expect(decision).toEqual({ ok: true, value: { kind: 'noop-empty-timeline' } });
  });

  it('togglePlay stops while playing and restarts from zero at the end', () => {
    expect(decideTogglePlay({
      currentlyPlaying: true,
      currentPlayheadMs: 3000,
      livePlayheadMs: 3000,
      timelineDurationMs: 8000,
    })).toEqual({ ok: true, value: { kind: 'stop' } });

    const restart = decideTogglePlay({
      currentlyPlaying: false,
      currentPlayheadMs: 8000,
      livePlayheadMs: 8000,
      timelineDurationMs: 8000,
    });
    expect(restart).toEqual({ ok: true, value: { kind: 'start', originPlayheadMs: 0, commitPlayhead: true } });
  });

  it('togglePlay skips the store commit for sub-millisecond moves', () => {
    const decision = decideTogglePlay({
      currentlyPlaying: false,
      currentPlayheadMs: 1000,
      livePlayheadMs: 1000.5,
      timelineDurationMs: 8000,
    });
    expect(decision).toEqual({
      ok: true,
      value: { kind: 'start', originPlayheadMs: 1000.5, commitPlayhead: false },
    });
  });

  it('rejects invalid durations and playheads', () => {
    expect(decideTogglePlay({
      currentlyPlaying: false,
      currentPlayheadMs: 0,
      livePlayheadMs: 0,
      timelineDurationMs: Number.NaN,
    })).toEqual({ ok: false, reason: 'invalid-duration' });
    expect(decideTogglePlay({
      currentlyPlaying: false,
      currentPlayheadMs: 0,
      livePlayheadMs: 0,
      timelineDurationMs: -5,
    })).toEqual({ ok: false, reason: 'invalid-duration' });
    expect(decideSeekTo({
      nextPlayheadMs: Number.POSITIVE_INFINITY,
      preservePlayback: false,
      commit: true,
      currentlyPlaying: false,
      currentPlayheadMs: 0,
      timelineDurationMs: 8000,
      hasActiveVideoEntry: true,
      nowMs: 1000,
    })).toEqual({ ok: false, reason: 'non-finite-playhead' });
  });

  it('seekTo clamps to [0, duration] and flags scrubbing when not committing', () => {
    const upper = decideSeekTo({
      nextPlayheadMs: 99999,
      preservePlayback: false,
      commit: true,
      currentlyPlaying: false,
      currentPlayheadMs: 0,
      timelineDurationMs: 8000,
      hasActiveVideoEntry: true,
      nowMs: 1000,
    });
    expect(upper).toEqual({
      ok: true,
      value: {
        boundedPlayheadMs: 8000,
        continuePlayback: false,
        forceSeek: true,
        scrubbing: false,
        commitPlayhead: true,
        gapAnchor: null,
        stopPlaying: false,
      },
    });

    const scrub = decideSeekTo({
      nextPlayheadMs: -50,
      preservePlayback: false,
      commit: false,
      currentlyPlaying: false,
      currentPlayheadMs: 100,
      timelineDurationMs: 8000,
      hasActiveVideoEntry: true,
      nowMs: 1000,
    });
    expect(scrub.ok && scrub.value.boundedPlayheadMs).toBe(0);
    expect(scrub.ok && scrub.value.scrubbing).toBe(true);
    expect(scrub.ok && scrub.value.commitPlayhead).toBe(false);
  });

  it('seekTo while playing with preserve opens a gap anchor off video', () => {
    const gap: GapAnchor = { originPlayheadMs: 6000, startedAt: 1000 };
    const decision = decideSeekTo({
      nextPlayheadMs: 6000,
      preservePlayback: true,
      commit: true,
      currentlyPlaying: true,
      currentPlayheadMs: 1000,
      timelineDurationMs: 8000,
      hasActiveVideoEntry: false,
      nowMs: 1000,
    });
    expect(decision).toEqual({
      ok: true,
      value: {
        boundedPlayheadMs: 6000,
        continuePlayback: true,
        forceSeek: true,
        scrubbing: false,
        commitPlayhead: true,
        gapAnchor: gap,
        stopPlaying: false,
      },
    });
  });

  it('paused seek while playing stops playback without an anchor', () => {
    const decision = decideSeekTo({
      nextPlayheadMs: 2000,
      preservePlayback: false,
      commit: true,
      currentlyPlaying: true,
      currentPlayheadMs: 1000,
      timelineDurationMs: 8000,
      hasActiveVideoEntry: false,
      nowMs: 1000,
    });
    expect(decision.ok && decision.value.continuePlayback).toBe(false);
    expect(decision.ok && decision.value.stopPlaying).toBe(true);
    expect(decision.ok && decision.value.gapAnchor).toBeNull();
  });

  it('seekBy routes through the live playhead and no-ops when empty', () => {
    expect(decideSeekBy({
      deltaMs: 500,
      livePlayheadMs: 1000,
      currentlyPlaying: true,
      timelineDurationMs: 0,
    })).toEqual({ ok: true, value: { kind: 'noop-empty-timeline' } });
    expect(decideSeekBy({
      deltaMs: Number.NaN,
      livePlayheadMs: 1000,
      currentlyPlaying: false,
      timelineDurationMs: 8000,
    })).toEqual({ ok: false, reason: 'non-finite-delta' });
    expect(decideSeekBy({
      deltaMs: -250,
      livePlayheadMs: 1000,
      currentlyPlaying: true,
      timelineDurationMs: 8000,
    })).toEqual({ ok: true, value: { kind: 'seek', targetPlayheadMs: 750, preservePlayback: true } });
  });

  it('finishPlayback falls back to the live playhead and clamps', () => {
    const decision = decideFinishPlayback({
      finalPlayheadMs: null,
      livePlayheadMs: 99999,
      currentPlayheadMs: 0,
      currentlyPlaying: true,
      timelineDurationMs: 8000,
    });
    expect(decision).toEqual({
      ok: true,
      value: { boundedPlayheadMs: 8000, commitPlayhead: true, stopPlaying: true },
    });
    expect(decideFinishPlayback({
      finalPlayheadMs: Number.NaN,
      livePlayheadMs: 100,
      currentPlayheadMs: 100,
      currentlyPlaying: false,
      timelineDurationMs: 8000,
    })).toEqual({ ok: false, reason: 'non-finite-playhead' });
  });

  it('commit guards and clamps match the hook thresholds', () => {
    expect(shouldCommitPlayhead(1000, 1000.999)).toBe(false);
    expect(shouldCommitPlayhead(1000, 1001)).toBe(true);
    expect(clampPlayhead(-20, 8000)).toBe(0);
    expect(clampPlayhead(9000, 8000)).toBe(8000);
  });
});

describe('playbackClock frame step', () => {
  const gapInput = {
    livePlayheadMs: 6000,
    timelineDurationMs: 8000,
    playbackEntries: [] as PlaybackTimelineEntry[],
    timestamp: 1200,
    gapAnchor: null as GapAnchor | null,
    media: readyMedia(),
  };

  it('finishes when the live playhead reached the duration', () => {
    expect(advancePlaybackFrame({ ...gapInput, livePlayheadMs: 8000 })).toEqual({
      kind: 'finish',
      playheadMs: 8000,
    });
  });

  it('opens a gap anchor from the frame timestamp and advances by wall clock', () => {
    const first = advancePlaybackFrame(gapInput);
    expect(first).toEqual({
      kind: 'advance-gap',
      nextPlayheadMs: 6000,
      gapAnchor: { originPlayheadMs: 6000, startedAt: 1200 },
    });
    if (first.kind !== 'advance-gap') {
      throw new Error('expected advance-gap');
    }
    const second = advancePlaybackFrame({
      ...gapInput,
      timestamp: 1700,
      gapAnchor: first.gapAnchor,
    });
    expect(second).toEqual({
      kind: 'advance-gap',
      nextPlayheadMs: 6500,
      gapAnchor: first.gapAnchor,
    });
  });

  it('finishes from a gap once the wall clock passes the duration', () => {
    const anchor: GapAnchor = { originPlayheadMs: 7900, startedAt: 1000 };
    expect(advancePlaybackFrame({ ...gapInput, timestamp: 1200, gapAnchor: anchor })).toEqual({
      kind: 'finish',
      playheadMs: 8000,
    });
  });

  it('waits while the media element is not observable', () => {
    const base = { ...gapInput, livePlayheadMs: 1000, playbackEntries: [makeEntry()] };
    for (const media of [
      readyMedia({ hasElement: false }),
      readyMedia({ videoReady: false }),
      readyMedia({ readyState: 1 }),
      readyMedia({ seeking: true }),
      readyMedia({ currentTime: Number.NaN }),
    ]) {
      expect(advancePlaybackFrame({ ...base, media }).kind).toBe('wait-video');
    }
  });

  it('drives the playhead from media time', () => {
    const entry = makeEntry(makeClip({ startMs: 1000, inPointMs: 5000, outPointMs: 9000 }));
    const decision = advancePlaybackFrame({
      livePlayheadMs: 1500,
      timelineDurationMs: 20000,
      playbackEntries: [entry],
      timestamp: 2000,
      gapAnchor: null,
      media: readyMedia({ currentTime: 6 }),
    });
    expect(decision.kind).toBe('drive-media');
    if (decision.kind !== 'drive-media') {
      throw new Error('expected drive-media');
    }
    expect(decision.playheadMs).toBe(2000);
    expect(decision.reachedClipEnd).toBe(false);
    expect(decision.startGap).toBe(false);
  });

  it('snaps to the clip end inside the epsilon window and opens a gap', () => {
    const entry = makeEntry(makeClip({ startMs: 0, inPointMs: 0, outPointMs: 5000 }));
    const decision = advancePlaybackFrame({
      livePlayheadMs: 1000,
      timelineDurationMs: 20000,
      playbackEntries: [entry],
      timestamp: 2000,
      gapAnchor: null,
      media: readyMedia({ currentTime: 4.995 }),
    });
    expect(decision.kind).toBe('drive-media');
    if (decision.kind !== 'drive-media') {
      throw new Error('expected drive-media');
    }
    expect(decision.playheadMs).toBe(5000);
    expect(decision.reachedClipEnd).toBe(true);
    expect(decision.startGap).toBe(true);
  });

  it('drives the frame scheduler on the injected port', () => {
    const seen: number[] = [];
    const errors: unknown[] = [];
    const scheduled: Array<(timestamp: number) => void> = [];
    const stop = drivePlaybackClock(
      {
        requestFrame: (callback) => {
          scheduled.push(callback);
          return scheduled.length;
        },
        cancelFrame: () => undefined,
      },
      (error) => {
        errors.push(error);
      },
      (timestamp) => {
        seen.push(timestamp);
        return seen.length < 2;
      },
    );
    expect(scheduled).toHaveLength(1);
    scheduled[0](10);
    expect(scheduled).toHaveLength(2);
    scheduled[1](20);
    expect(scheduled).toHaveLength(2);
    expect(seen).toEqual([10, 20]);
    stop();
    expect(errors).toEqual([]);
  });

  it('routes step failures to onError without rescheduling', () => {
    const errors: unknown[] = [];
    let scheduled = 0;
    drivePlaybackClock(
      {
        requestFrame: (callback) => {
          scheduled += 1;
          callback(0);
          return scheduled;
        },
        cancelFrame: () => undefined,
      },
      (error) => {
        errors.push(error);
      },
      () => {
        throw new Error('boom');
      },
    );
    expect(errors).toHaveLength(1);
    expect(scheduled).toBe(1);
  });
});

describe('playbackService orchestrator', () => {
  it('togglePlay no-ops on an empty timeline without side effects', () => {
    const state = makeState({ timelineDurationMs: 0, isPlaying: false });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports);
    expect(service.togglePlay()).toEqual({ ok: true, value: { kind: 'noop-empty-timeline' } });
    expect(fake.playheadWrites).toEqual([]);
    expect(fake.playingWrites).toEqual([]);
    expect(fake.transports).toEqual([]);
  });

  it('togglePlay starts playback, commits, and emits transport plus preview once', () => {
    const state = makeState({ isPlaying: false, playheadMs: 500, timelineDurationMs: 8000 });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports, 1200);
    const outcome = service.togglePlay();
    expect(outcome).toEqual({ ok: true, value: { kind: 'started', originPlayheadMs: 1200, committedPlayhead: true } });
    expect(fake.playheadWrites).toEqual([1200]);
    expect(fake.playingWrites).toEqual([true]);
    expect(fake.transports).toHaveLength(1);
    expect(fake.transports[0]).toMatchObject({ playheadMs: 1200, mode: 'playing' });
    expect(fake.previews).toHaveLength(1);
    expect(service.getLivePlayheadMs()).toBe(1200);
  });

  it('togglePlay while playing takes the stop path', () => {
    const state = makeState({ isPlaying: true, playheadMs: 1200, timelineDurationMs: 8000 });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports, 1200);
    const outcome = service.togglePlay();
    expect(outcome.ok && outcome.value.kind).toBe('stopped');
    expect(fake.playingWrites).toEqual([false]);
  });

  it('seekTo clamps, commits, and flags scrubbing when not committing', () => {
    const state = makeState({ isPlaying: false, playheadMs: 100 });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports, 100);
    const committed = service.seekTo(99999);
    expect(committed.ok && committed.value.boundedPlayheadMs).toBe(8000);
    expect(fake.playheadWrites).toEqual([8000]);

    const scrubbed = service.seekTo(4000, false, false);
    expect(scrubbed.ok && scrubbed.value.committedPlayhead).toBe(false);
    expect(fake.transports.at(-1)).toMatchObject({ playheadMs: 4000, mode: 'scrubbing' });
    expect(fake.playheadWrites).toEqual([8000]);
  });

  it('seekTo rejects non-finite input without side effects', () => {
    const state = makeState();
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports);
    expect(service.seekTo(Number.NaN)).toEqual({ ok: false, reason: 'non-finite-playhead' });
    expect(fake.transports).toEqual([]);
    expect(fake.playheadWrites).toEqual([]);
  });

  it('seekBy preserves playback and stopPlayback finishes at live', () => {
    const state = makeState({ isPlaying: true, playheadMs: 1000 });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports, 1000);
    const moved = service.seekBy(500);
    expect(moved.ok && moved.value).toMatchObject({ boundedPlayheadMs: 1500, continuePlayback: true });

    const stopped = service.stopPlayback();
    expect(stopped.ok && stopped.value.boundedPlayheadMs).toBe(1500);
    expect(fake.playingWrites).toContain(false);
  });

  it('dedups repeated preview emissions for the same asset', () => {
    const state = makeState();
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports);
    service.seekTo(1000);
    service.seekTo(1500);
    expect(fake.previews).toHaveLength(1);
    service.seekTo(9000);
    expect(fake.previews).toHaveLength(2);
  });

  it('steps the clock across a gap with the fake clock and frame port', () => {
    const state = makeState({ isPlaying: true, playheadMs: 6000, playbackEntries: [] });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports, 6000);
    const stop = service.startClock(() => readyMedia());
    expect(fake.frames.pending.size).toBe(1);

    fake.setNow(1000);
    fake.frames.fireAll(1000);
    expect(service.getLivePlayheadMs()).toBe(6000);

    fake.frames.fireAll(1500);
    expect(service.getLivePlayheadMs()).toBe(6500);
    expect(fake.transports.at(-1)).toMatchObject({ playheadMs: 6500, mode: 'playing' });

    stop();
    expect(fake.frames.cancelled).toHaveLength(1);
    expect(fake.frames.pending.size).toBe(0);
    expect(fake.clockErrors).toEqual([]);
  });

  it('stepClock drives media time and finishes at the duration', () => {
    const entry = makeEntry(makeClip({ startMs: 0, inPointMs: 0, outPointMs: 8000 }));
    const state = makeState({ isPlaying: true, playheadMs: 1000, playbackEntries: [entry] });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports, 1000);
    const snapshot = service.stepClock(2000, readyMedia({ currentTime: 2 }));
    expect(snapshot?.activeVideoEntry?.clip.id).toBe('c1');
    expect(service.getLivePlayheadMs()).toBe(2000);

    const finishState = makeState({ isPlaying: true, playheadMs: 7990, playbackEntries: [entry] });
    const finishFake = createFakePorts(finishState);
    const finishService = createPlaybackService(finishFake.ports, 7990);
    expect(finishService.stepClock(3000, readyMedia({ currentTime: 7.999 }))).toBeNull();
    expect(finishFake.playingWrites).toEqual([false]);
    expect(finishFake.playheadWrites).toEqual([8000]);
  });

  it('syncPausedTransport clears the gap anchor and emits paused mode', () => {
    const state = makeState({ isPlaying: false, playheadMs: 500 });
    const fake = createFakePorts(state);
    const service = createPlaybackService(fake.ports, 1200);
    const result = service.syncPausedTransport(500);
    expect(result.emission.boundedPlayheadMs).toBe(500);
    expect(result.emission.transport.mode).toBe('paused');
    expect(service.getLivePlayheadMs()).toBe(500);
  });
});
