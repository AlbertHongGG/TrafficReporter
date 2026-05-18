import type {
  LprFrameSample,
  LprPlateCandidate,
  LprRuntimeStatus,
  LprSessionState,
  TimelineIntervalSelection,
} from '../../../shared/contracts';

export const MAIN_WINDOW_LABEL = 'main';
export const PLATE_WINDOW_LABEL = 'plate';
export const PLATE_WINDOW_URL = 'plate.html';
export const PLATE_SESSION_UPDATED_EVENT = 'editor/plate-session-updated';
export const PLATE_SESSION_REQUEST_EVENT = 'editor/plate-session-request';
export const PLATE_ACTION_EVENT = 'editor/plate-action';

export interface PlateWindowSessionSnapshot {
  workspaceName: string;
  activeFileName: string | null;
  hasActiveFile: boolean;
  runtimeStatus: LprRuntimeStatus | null;
  lpr: LprSessionState;
  explicitInterval: TimelineIntervalSelection | null;
  effectiveInterval: TimelineIntervalSelection | null;
  canAnalyzeRange: boolean;
  topCandidate: LprPlateCandidate | null;
  anchorTimeMs: number;
  playheadMs: number;
}

export type PlateWindowAction =
  | { type: 'refresh-runtime' }
  | { type: 'cancel-job' }
  | { type: 'use-clip-interval' }
  | { type: 'set-interval-boundary'; boundary: 'start' | 'end' }
  | { type: 'clear-interval' }
  | { type: 'set-analysis-profile'; analysisProfileId: string }
  | { type: 'set-country-hints'; value: string }
  | { type: 'scan-targets' }
  | { type: 'analyze-frame' }
  | { type: 'analyze-range' }
  | { type: 'toggle-dense-sampling' }
  | { type: 'toggle-developer-diagnostics' }
  | { type: 'export-evidence' }
  | { type: 'clear-results' }
  | { type: 'select-target-track'; targetTrackId: string; anchorTimeMs: number }
  | { type: 'accept-candidate'; candidateId: string }
  | { type: 'seek-to-sample'; sampleId: string; timeMs: number };

export function samplePrimaryText(sample: LprFrameSample) {
  return sample.candidates[0]?.text ?? '--';
}
