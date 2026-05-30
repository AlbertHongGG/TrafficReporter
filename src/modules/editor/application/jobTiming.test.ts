import { describe, expect, it } from 'vitest';

import { buildJobTimingSnapshot, formatElapsedDuration } from './jobTiming';

describe('jobTiming', () => {
  it('tracks total runtime and current-step idle time for active jobs', () => {
    expect(buildJobTimingSnapshot({
      status: 'running',
      startedAt: '2026-05-30T00:00:00.000Z',
      updatedAt: '2026-05-30T00:00:08.000Z',
    }, Date.parse('2026-05-30T00:00:12.000Z'))).toEqual({
      totalElapsedMs: 12_000,
      idleSinceUpdateMs: 4_000,
      isStalled: false,
    });
  });

  it('flags active jobs that have stopped reporting progress', () => {
    expect(buildJobTimingSnapshot({
      status: 'queued',
      startedAt: '2026-05-30T00:00:00.000Z',
      updatedAt: '2026-05-30T00:00:01.000Z',
    }, Date.parse('2026-05-30T00:00:12.000Z'), 5_000).isStalled).toBe(true);
  });

  it('freezes completed runtime at the last update timestamp', () => {
    expect(buildJobTimingSnapshot({
      status: 'completed',
      startedAt: '2026-05-30T00:00:00.000Z',
      updatedAt: '2026-05-30T00:00:09.000Z',
    }, Date.parse('2026-05-30T00:01:00.000Z'))).toEqual({
      totalElapsedMs: 9_000,
      idleSinceUpdateMs: null,
      isStalled: false,
    });
  });

  it('formats short and long durations for status chips', () => {
    expect(formatElapsedDuration(1_250)).toBe('1.3s');
    expect(formatElapsedDuration(65_000)).toBe('1:05');
  });
});