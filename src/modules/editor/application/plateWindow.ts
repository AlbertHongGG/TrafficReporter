import type {
  LprFrameSample,
  LprPlateCandidate,
  LprReviewState,
  LprSessionState,
  TimelineIntervalSelection,
} from '../domain/model';
import type { VersionedPayload } from '../../../platform/desktop';
import type { WorkspaceRuntimeSnapshot } from '../../../platform/transport/types';
import { resolveEffectivePlayheadMs, type LiveTransportSnapshot } from './liveTransport';

export const MAIN_WINDOW_LABEL = 'main';
export const PLATE_WINDOW_LABEL = 'plate';
export const PLATE_WINDOW_URL = 'index.html?window=plate';
export const PLATE_SESSION_UPDATED_EVENT = 'editor/plate-session-updated';
export const PLATE_SESSION_REQUEST_EVENT = 'editor/plate-session-request';
export const PLATE_ACTION_EVENT = 'editor/plate-action';
export const PLATE_LIVE_TRANSPORT_EVENT = 'editor/plate-live-transport';

/**
 * Plate 快照＝共用 WorkspaceRuntimeSnapshot 基底＋plate 自身欄位（Blueprint §5.3）。
 * liveTransport 在 plate 以獨立 live 通道傳遞，主視窗 builder 不攜帶，
 * 故此處以可選保留（缺席視為無 live 疊加），其餘共用欄位語義不變。
 */
export type PlateWindowSessionSnapshot = Omit<WorkspaceRuntimeSnapshot, 'liveTransport'> & {
  readonly liveTransport?: LiveTransportSnapshot | null;
  readonly lpr: LprSessionState;
  readonly explicitInterval: TimelineIntervalSelection | null;
  readonly effectiveInterval: TimelineIntervalSelection | null;
  readonly canAnalyzeRange: boolean;
  readonly topCandidate: LprPlateCandidate | null;
  readonly anchorTimeMs: number;
};

export type RevisionedPlateWindowSessionSnapshot = VersionedPayload<PlateWindowSessionSnapshot>;

export type PlateWindowLiveTransport = LiveTransportSnapshot;

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

export function resolveLprDisplayCandidate(
  candidates: LprPlateCandidate[],
  review: LprReviewState | null | undefined,
  acceptedCandidateId: string | null | undefined,
) {
  return candidates.find((candidate) => candidate.id === acceptedCandidateId)
    ?? candidates.find((candidate) => candidate.id === review?.acceptedCandidateId)
    ?? candidates.find((candidate) => candidate.id === review?.suggestedCandidateId)
    ?? candidates[0]
    ?? null;
}

export function resolvePlateWindowPlayheadMs(
  snapshot: PlateWindowSessionSnapshot | null,
  liveTransport: PlateWindowLiveTransport | null,
) {
  return resolveEffectivePlayheadMs(snapshot?.playheadMs ?? 0, liveTransport);
}
