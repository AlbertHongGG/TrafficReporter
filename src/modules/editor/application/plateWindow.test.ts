import { describe, expect, it } from 'vitest';

import { buildDefaultLprState } from '../domain/lprState';
import {
  resolvePlateWindowPlayheadMs,
  type PlateWindowSessionSnapshot,
} from './plateWindow';

function buildSnapshot(playheadMs: number): PlateWindowSessionSnapshot {
  return {
    workspaceName: 'Traffic',
    activeFileName: 'demo.mp4',
    hasActiveFile: true,
    runtimeStatus: null,
    lpr: buildDefaultLprState(),
    explicitInterval: null,
    effectiveInterval: null,
    canAnalyzeRange: false,
    topCandidate: null,
    anchorTimeMs: playheadMs,
    playheadMs,
  };
}

describe('plateWindow live playhead resolution', () => {
  it('falls back to the committed session playhead when no live transport exists', () => {
    expect(resolvePlateWindowPlayheadMs(buildSnapshot(860), null)).toBe(860);
  });

  it('uses the live transport playhead during active scrub or playback', () => {
    expect(resolvePlateWindowPlayheadMs(buildSnapshot(860), {
      playheadMs: 1240,
      mode: 'scrubbing',
      updatedAt: '2026-05-28T00:00:00.000Z',
    })).toBe(1240);
  });
});