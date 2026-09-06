import { describe, expect, it } from 'vitest';
import {
  createVersionedPayload,
  isVersionedPayload,
  shouldApplyVersion,
  unwrapVersionedPayload,
} from './desktopSync';

describe('desktopSync', () => {
  it('creates versioned payload with truncated non-negative version', () => {
    const payload = createVersionedPayload({ count: 42 }, 3.9, '2026-09-07T00:00:00.000Z');
    expect(payload).toEqual({
      version: 3,
      timestamp: '2026-09-07T00:00:00.000Z',
      payload: { count: 42 },
    });

    const negative = createVersionedPayload('data', -2);
    expect(negative.version).toBe(0);
  });

  it('validates versioned payload shape', () => {
    expect(isVersionedPayload(null)).toBe(false);
    expect(isVersionedPayload({ count: 1 })).toBe(false);
    expect(isVersionedPayload({ version: 1, payload: 'data' })).toBe(true);
  });

  it('unwraps raw and versioned values reliably', () => {
    const wrapped = createVersionedPayload('hello', 5, 'ts');
    expect(unwrapVersionedPayload(wrapped)).toBe(wrapped);

    const unwrapped = unwrapVersionedPayload('raw');
    expect(unwrapped.version).toBe(0);
    expect(unwrapped.payload).toBe('raw');
  });

  it('enforces monotonic version order', () => {
    expect(shouldApplyVersion(2, 3)).toBe(true);
    expect(shouldApplyVersion(3, 3)).toBe(true);
    expect(shouldApplyVersion(3, 2)).toBe(false);
  });
});
