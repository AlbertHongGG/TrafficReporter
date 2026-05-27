import { describe, expect, it, vi } from 'vitest';

import {
  buildLiveTransportSnapshot,
  createLiveTransportStore,
  resolveEffectivePlayheadMs,
  resolveLiveTransportMode,
} from './liveTransport';

describe('liveTransport', () => {
  it('resolves playing, scrubbing, and paused modes explicitly', () => {
    expect(resolveLiveTransportMode(true, true)).toBe('playing');
    expect(resolveLiveTransportMode(false, true)).toBe('scrubbing');
    expect(resolveLiveTransportMode(false, false)).toBe('paused');
  });

  it('notifies subscribers only when position or mode changes', () => {
    const store = createLiveTransportStore({ playheadMs: 1200, mode: 'paused' });
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    store.publish(buildLiveTransportSnapshot(1200, 'paused', '2026-05-28T00:00:00.000Z'));
    expect(listener).not.toHaveBeenCalled();

    store.publish(buildLiveTransportSnapshot(1280, 'scrubbing', '2026-05-28T00:00:00.100Z'));
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()).toMatchObject({ playheadMs: 1280, mode: 'scrubbing' });

    unsubscribe();
    store.publish(buildLiveTransportSnapshot(1320, 'scrubbing', '2026-05-28T00:00:00.200Z'));
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('prefers live transport playhead over committed playhead when available', () => {
    expect(resolveEffectivePlayheadMs(900, null)).toBe(900);
    expect(resolveEffectivePlayheadMs(900, { playheadMs: 1234 })).toBe(1234);
  });
});