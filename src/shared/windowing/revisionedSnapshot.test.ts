import { describe, expect, it } from 'vitest';
import {
  createRevisionedWindowSnapshot,
  shouldApplyRevisionedWindowSnapshot,
  unwrapRevisionedWindowSnapshot,
} from './revisionedSnapshot';

describe('revisionedSnapshot', () => {
  it('wraps and unwraps revisioned window snapshots', () => {
    const wrapped = createRevisionedWindowSnapshot({ activeFileName: 'demo.mp4' }, 4, '2026-05-27T00:00:00.000Z');
    const unwrapped = unwrapRevisionedWindowSnapshot(wrapped);

    expect(unwrapped.revision).toBe(4);
    expect(unwrapped.snapshot.activeFileName).toBe('demo.mp4');
  });

  it('treats legacy snapshots as revision zero', () => {
    const unwrapped = unwrapRevisionedWindowSnapshot({ activeFileName: 'legacy.mp4' });

    expect(unwrapped.revision).toBe(0);
    expect(unwrapped.snapshot.activeFileName).toBe('legacy.mp4');
  });

  it('rejects stale revisions', () => {
    expect(shouldApplyRevisionedWindowSnapshot(5, 4)).toBe(false);
    expect(shouldApplyRevisionedWindowSnapshot(5, 5)).toBe(true);
    expect(shouldApplyRevisionedWindowSnapshot(5, 6)).toBe(true);
  });
});
