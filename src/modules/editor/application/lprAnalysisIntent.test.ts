import { describe, expect, it } from 'vitest';
import { resolveLprRangeAnalysisIntent } from './lprAnalysisIntent';

describe('resolveLprRangeAnalysisIntent', () => {
  it('uses the runtime short-range intent for short intervals regardless of dense mode', () => {
    expect(resolveLprRangeAnalysisIntent(3000, false)).toBe('interactive-short-range');
    expect(resolveLprRangeAnalysisIntent(3500, true)).toBe('interactive-short-range');
  });

  it('preserves dense intent for longer intervals', () => {
    expect(resolveLprRangeAnalysisIntent(3501, false)).toBe('interactive-range');
    expect(resolveLprRangeAnalysisIntent(3501, true)).toBe('interactive-dense-range');
  });
});