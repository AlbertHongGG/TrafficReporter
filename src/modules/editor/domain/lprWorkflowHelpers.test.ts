import { describe, expect, it } from 'vitest';
import type { LprPlateCandidate } from './lprState';
import {
  formatLprReviewReason,
  buildLprCompletionDetail,
  buildTargetTracksFromDetections,
  normalizeLprInterval,
  isAnchorWithinInterval,
  resolveStageStartedAt,
} from './lprWorkflowHelpers';

describe('lprWorkflowHelpers', () => {
  it('formats known and unknown review reasons properly', () => {
    expect(formatLprReviewReason('low-confidence')).toBe('confidence stayed low');
    expect(formatLprReviewReason('low-margin')).toBe('the runner-up stayed too close');
    expect(formatLprReviewReason('insufficient-support')).toBe('too few sampled frames agreed');
    expect(formatLprReviewReason('format-mismatch')).toBe('the plate pattern looked off');
    expect(formatLprReviewReason('no-candidate')).toBe('no readable candidate was found');
    expect(formatLprReviewReason('custom-reason-code')).toBe('custom reason code');
  });

  it('builds completion detail for accepted candidate', () => {
    const candidates = [
      { id: 'c1', text: 'ABC-1234', confidence: 0.95 } as unknown as LprPlateCandidate,
    ];
    const detail = buildLprCompletionDetail(candidates, { status: 'accepted', acceptedCandidateId: 'c1', suggestedCandidateId: null, reasons: [] });
    expect(detail).toBe('Accepted ABC-1234');
  });

  it('builds completion detail when review is required', () => {
    const candidates = [
      { id: 'c1', text: 'ABC-1234', confidence: 0.7 } as unknown as LprPlateCandidate,
    ];
    const detail = buildLprCompletionDetail(candidates, {
      status: 'review-required',
      acceptedCandidateId: 'c1',
      suggestedCandidateId: 'c1',
      reasons: ['low-confidence'],
    });
    expect(detail).toContain('Auto-accept is paused because confidence stayed low.');
  });

  it('normalizes interval correctly handling inverted ranges', () => {
    expect(normalizeLprInterval({ startMs: 5000, endMs: 2000 })).toEqual({ startMs: 2000, endMs: 5000 });
    expect(normalizeLprInterval({ startMs: -10, endMs: 300 })).toEqual({ startMs: 0, endMs: 300 });
  });

  it('checks if anchor is within interval', () => {
    const interval = { startMs: 1000, endMs: 5000 };
    expect(isAnchorWithinInterval(1000, interval)).toBe(true);
    expect(isAnchorWithinInterval(3000, interval)).toBe(true);
    expect(isAnchorWithinInterval(5000, interval)).toBe(true);
    expect(isAnchorWithinInterval(999, interval)).toBe(false);
    expect(isAnchorWithinInterval(5001, interval)).toBe(false);
  });

  it('converts tracked detections into target tracks', () => {
    const detections = [
      { id: 'det-1', className: 'Car', confidence: 0.9, box: { x: 0, y: 0, width: 0.2, height: 0.2 }, timeMs: 100 },
    ];
    const tracks = buildTargetTracksFromDetections(detections);
    expect(tracks).toHaveLength(1);
    expect(tracks[0].id).toBe('det-1');
    expect(tracks[0].label).toBe('Car 1');
  });

  it('resets stage clock on stage change', () => {
    const now = '2026-09-06T00:00:00.000Z';
    const started = resolveStageStartedAt(
      { status: 'running', stage: 'Scan', requestId: 'req-1', startedAt: now, stageStartedAt: now },
      { stage: 'Track' },
      '2026-09-06T00:00:05.000Z',
    );
    expect(started).toBe('2026-09-06T00:00:05.000Z');
  });
});
