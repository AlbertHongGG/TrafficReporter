import { describe, expect, it } from 'vitest';

import { buildDefaultLprState } from '../domain/lprState';
import {
  resolveLprDisplayCandidate,
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

describe('plateWindow display candidate resolution', () => {
  it('uses the runtime suggested candidate when no candidate is accepted', () => {
    const noisyCandidate = {
      id: 'single-char',
      text: '4',
      confidence: 0.69,
      source: 'fused' as const,
      frameTimeMs: 2288,
      countryCode: 'TW',
      box: null,
      quality: null,
      diagnostics: null,
    };
    const suggestedCandidate = {
      ...noisyCandidate,
      id: 'plate-like',
      text: 'RJE5752',
      confidence: 0.51,
    };

    expect(resolveLprDisplayCandidate([noisyCandidate, suggestedCandidate], {
      status: 'review-required',
      acceptedCandidateId: null,
      suggestedCandidateId: 'plate-like',
      reasons: ['unstable-sequence'],
    }, null)?.text).toBe('RJE5752');
  });
});