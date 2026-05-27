function readIntegerEnv(value: string | undefined, fallback: number, minimum = 0) {
  const parsed = Number.parseInt(value ?? '', 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(minimum, parsed);
}

export const EDITOR_ENV = {
  lprTargetOverlayToleranceMs: readIntegerEnv(import.meta.env.VITE_LPR_TARGET_OVERLAY_TOLERANCE_MS, 360, 0),
  lprAnalysisInterpolationGapMs: readIntegerEnv(import.meta.env.VITE_LPR_ANALYSIS_INTERPOLATION_GAP_MS, 260, 0),
} as const;