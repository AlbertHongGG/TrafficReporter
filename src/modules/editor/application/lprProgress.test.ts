import { describe, expect, it } from 'vitest'

import { buildLprJobUpdateFromProgress, shouldApplyLprProgress } from './lprProgress'

describe('lprProgress', () => {
  it('ignores progress for a different active request', () => {
    expect(shouldApplyLprProgress('req-active', {
      requestId: 'req-other',
      progress: 0.3,
      stage: 'Frame',
      detail: 'Running',
      done: false,
      failed: false,
      reasonCode: null,
      trackingTier: null,
      coverageRatio: null,
    })).toBe(false)
  })

  it('maps in-flight progress into a running job update', () => {
    expect(buildLprJobUpdateFromProgress('req-001', {
      requestId: 'req-001',
      progress: 1.2,
      stage: 'Frame',
      detail: 'Locating target',
      done: false,
      failed: false,
      reasonCode: null,
      trackingTier: null,
      coverageRatio: null,
    })).toEqual({
      status: 'running',
      progress: 1,
      stage: 'Frame',
      detail: 'Locating target',
      requestId: 'req-001',
      error: null,
      reasonCode: null,
      trackingTier: null,
      coverageRatio: null,
    })
  })

  it('maps completed partial coverage into a degraded job update', () => {
    expect(buildLprJobUpdateFromProgress('req-002', {
      requestId: 'req-002',
      progress: 1,
      stage: 'Interval',
      detail: 'Coverage 60% (detection-fallback).',
      done: true,
      failed: false,
      reasonCode: 'coverage-gap',
      trackingTier: 'detection-fallback',
      coverageRatio: 0.6,
    })).toEqual({
      status: 'degraded',
      progress: 1,
      stage: 'Interval',
      detail: 'Coverage 60% (detection-fallback).',
      requestId: 'req-002',
      error: null,
      reasonCode: 'coverage-gap',
      trackingTier: 'detection-fallback',
      coverageRatio: 0.6,
    })
  })
})