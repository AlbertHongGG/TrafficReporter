import type { LprAnalysisIntent } from '../../../domain/ipc/bindings';

export const INTERACTIVE_RANGE_LATENCY_BUDGET_MS = 30_000;

export function resolveLprRangeAnalysisIntent(durationMs: number, useDenseSampling: boolean): LprAnalysisIntent {
  if (durationMs <= 3500) {
    return 'interactive-short-range';
  }
  return useDenseSampling ? 'interactive-dense-range' : 'interactive-range';
}