import type { LprJobState } from '../domain/model'
import type { LprProgress } from '../../../shared/contracts'

export function shouldApplyLprProgress(
  activeRequestId: string | null,
  progress: LprProgress,
): activeRequestId is string {
  if (!activeRequestId) {
    return false
  }

  return !progress.requestId || progress.requestId === activeRequestId
}

export function buildLprJobUpdateFromProgress(
  activeRequestId: string,
  progress: LprProgress,
): Partial<LprJobState> {
  return {
    status: progress.failed
      ? 'failed'
      : progress.done
        ? progress.trackingTier && progress.trackingTier !== 'full'
          ? 'degraded'
          : 'completed'
        : 'running',
    progress: Math.max(0, Math.min(1, progress.progress)),
    stage: progress.stage,
    detail: progress.detail,
    requestId: activeRequestId,
    error: progress.failed ? progress.detail : null,
    reasonCode: progress.reasonCode ?? null,
    trackingTier: progress.trackingTier ?? null,
    coverageRatio: progress.coverageRatio ?? null,
  }
}