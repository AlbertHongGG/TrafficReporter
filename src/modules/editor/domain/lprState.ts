import type {
  LprAnalysisIntent,
  LprAnalysisOptionsPayload,
  LprDecisionTrace,
  LprJobStatus,
  LprLegibilityLevel,
  LprOcrInput,
  LprReviewStatus,
  LprSampleSelection,
  LprSequenceSummary,
  LprTemporalSupport,
  LprTrackingSummary,
  LprTrackingTier,
  LprVehicleKind,
} from '../../../types/bindings';
import type { TimelineIntervalSelection, VideoMarkerRect } from './model';
import { defaultLprAnalysisProfileId, type LprAnalysisProfileId } from './lprProfiles';
import type { OutputCompressionMode } from '../../export/domain/model';

/**
 * Unstructured cross-process diagnostics (Blueprint §1.2).
 *
 * Specta emits these payloads as `any` because the backend holds them as
 * schemaless JSON. The frontend converges every such field onto this single
 * domain-wide type instead of scattering `any`. Consumers must narrow via
 * `unknown`-safe helpers (see `asRecord`/`asNumber` in the LPR panel).
 * Runtime boundary validation is Phase 2 (zod) scope — this type adds no
 * runtime checks and changes no behavior.
 */
export type Diagnostics = Record<string, unknown>;

export interface LprReviewState {
  status: LprReviewStatus;
  acceptedCandidateId: string | null;
  suggestedCandidateId: string | null;
  reasons: string[];
}

export interface LprAnalysisProvenance {
  requestId: string | null;
  command: string;
  analysisProfileId: LprAnalysisProfileId | null;
  developerDiagnosticsEnabled: boolean;
  runtimeVersion: string | null;
  restorationMode?: string | null;
  recognizerBackend?: string | null;
  temporalEvidenceMode?: string | null;
  sequenceReviewMode?: string | null;
  emittedAtMs: number;
}

export interface LprRuntimeStatus {
  available: boolean;
  pythonExecutable: string | null;
  runtimeScript: string | null;
  version: string | null;
  missingPackages: string[];
  installedPackages: string[];
  detail: string;
}

export interface LprProgressPayload {
  progress: number;
  stage: string;
  detail: string;
  done: boolean;
  failed: boolean;
  requestId: string | null;
  reasonCode?: string | null;
  trackingTier?: LprTrackingTier | null;
  coverageRatio?: number | null;
}
export type LprProgress = LprProgressPayload;

export type LprWorkflowMode = 'idle' | 'range' | 'target' | 'review';

export interface LprQualityMetrics {
  sharpness: number;
  contrast: number;
  plateArea: number;
  angleScore: number;
  occlusionScore: number;
  glareScore: number;
  legibilityScore: number;
  overallScore: number;
  legibilityLevel: LprLegibilityLevel;
}

export interface LprTrackedRegion {
  id: string;
  timeMs: number;
  box: VideoMarkerRect;
  confidence: number;
  className: string;
  diagnostics?: Diagnostics | null;
}

export interface LprTargetTrack {
  id: string;
  className: string;
  label: string;
  confidence: number;
  frames: LprTrackedRegion[];
  diagnostics?: Diagnostics | null;
}

export interface LprPlateCandidate {
  id: string;
  text: string;
  confidence: number;
  source: string;
  frameTimeMs: number | null;
  countryCode: string | null;
  box: VideoMarkerRect | null;
  quality: LprQualityMetrics | null;
  diagnostics?: Diagnostics | null;
}

export interface LprFrameSample {
  id: string;
  timeMs: number;
  targetBox?: VideoMarkerRect | null;
  plateBox?: VideoMarkerRect | null;
  quality?: LprQualityMetrics | null;
  selection?: LprSampleSelection | null;
  ocrInput?: LprOcrInput | null;
  temporalSupport?: LprTemporalSupport | null;
  diagnostics?: Diagnostics | null;
  imagePath?: string | null;
  candidates: LprPlateCandidate[];
}

export interface LprJobState {
  status: LprJobStatus;
  progress: number;
  stage: string;
  detail: string;
  requestId: string | null;
  error: string | null;
  reasonCode: string | null;
  startedAt: string | null;
  stageStartedAt: string | null;
  updatedAt: string | null;
  trackingTier?: LprTrackingTier | null;
  coverageRatio?: number | null;
}

export interface LprTargetAnchor {
  trackId: string;
  className: string;
  timeMs: number;
  box: VideoMarkerRect;
}

export interface LprResultHistoryEntry {
  id: string;
  createdAt: string;
  interval: TimelineIntervalSelection | null;
  targetTrackId: string | null;
  acceptedCandidateId: string | null;
  analysisProfileId: LprAnalysisProfileId | null;
  developerDiagnosticsEnabled: boolean;
  candidates: LprPlateCandidate[];
  summary: string;
}

export interface LprSessionState {
  workflowMode: LprWorkflowMode;
  interval: TimelineIntervalSelection | null;
  selectedAnalysisProfileId: LprAnalysisProfileId;
  showDeveloperDiagnostics: boolean;
  targetVehicleKind: LprVehicleKind;
  useDenseSampling: boolean;
  countryHints: string[];
  job: LprJobState;
  targetTracks: LprTargetTrack[];
  selectedTargetTrackId: string | null;
  selectedTargetAnchor: LprTargetAnchor | null;
  analysisTrack: LprTargetTrack | null;
  samples: LprFrameSample[];
  candidates: LprPlateCandidate[];
  review: LprReviewState | null;
  lastAnalysisProvenance: LprAnalysisProvenance | null;
  decision: LprDecisionTrace | null;
  acceptedCandidateId: string | null;
  history: LprResultHistoryEntry[];
}

export interface LprTargetScanRequest {
  sourcePath: string;
  timeMs: number;
  markerRect: VideoMarkerRect | null;
  targetVehicleKind: LprVehicleKind;
  requestId?: string | null;
}

export interface LprTargetScanResponse {
  detections: LprTrackedRegion[];
  runtime: LprRuntimeStatus;
}

export interface LprFrameAnalysisRequest {
  sourcePath: string;
  timeMs: number;
  markerRect: VideoMarkerRect | null;
  targetVehicleKind: LprVehicleKind;
  selectedTargetBox?: VideoMarkerRect | null;
  countryHints: string[];
  analysisProfileId?: LprAnalysisProfileId | null;
  enableDeveloperDiagnostics?: boolean;
  analysisOptions?: LprAnalysisOptionsPayload | null;
  requestId?: string | null;
}

export interface LprFrameAnalysisResponse {
  detections: LprTrackedRegion[];
  sample: LprFrameSample | null;
  candidates: LprPlateCandidate[];
  acceptedCandidateId: string | null;
  review: LprReviewState;
  provenance: LprAnalysisProvenance;
  decision: LprDecisionTrace | null;
  runtime: LprRuntimeStatus;
  jobStatus: LprJobStatus | null;
  diagnostics?: Diagnostics | null;
}

export interface LprIntervalAnalysisRequest {
  sourcePath: string;
  interval: TimelineIntervalSelection;
  anchorTimeMs: number;
  targetVehicleKind: LprVehicleKind;
  selectedTargetBox?: VideoMarkerRect | null;
  selectedTargetTrackId?: string | null;
  countryHints: string[];
  sampleEveryMs?: number | null;
  maxSamples?: number | null;
  analysisIntent?: LprAnalysisIntent | null;
  latencyBudgetMs?: number | null;
  analysisProfileId?: LprAnalysisProfileId | null;
  enableDeveloperDiagnostics?: boolean | null;
  analysisOptions?: LprAnalysisOptionsPayload | null;
  requestId?: string | null;
}

export interface LprIntervalAnalysisResponse {
  targetTracks: LprTargetTrack[];
  analysisTrack: LprTargetTrack | null;
  samples: LprFrameSample[];
  candidates: LprPlateCandidate[];
  acceptedCandidateId: string | null;
  review: LprReviewState;
  provenance: LprAnalysisProvenance;
  decision: LprDecisionTrace | null;
  summary: string;
  runtime: LprRuntimeStatus;
  jobStatus: LprJobStatus | null;
  tracking?: LprTrackingSummary | null;
  sequence?: LprSequenceSummary | null;
  diagnostics?: Diagnostics | null;
}

export interface LprEvidenceExportRequest {
  outputPath: string;
  sourcePath: string;
  timeMs: number;
  markerRect: VideoMarkerRect | null;
  compressionMode: OutputCompressionMode;
  interval?: TimelineIntervalSelection | null;
  targetTrack?: LprTargetTrack | null;
  acceptedCandidate?: LprPlateCandidate | null;
  candidates: LprPlateCandidate[];
  samples: LprFrameSample[];
  review?: LprReviewState | null;
  provenance?: LprAnalysisProvenance | null;
}

export interface LprEvidenceExportResponse {
  jsonPath: string;
  imagePath: string;
  bundleDir: string;
  exportedFileCount: number;
  decisionFrameCount: number;
}

export const DEFAULT_LPR_JOB_STATE: LprJobState = {
  status: 'idle',
  progress: 0,
  stage: '',
  detail: '',
  requestId: null,
  error: null,
  reasonCode: null,
  startedAt: null,
  stageStartedAt: null,
  updatedAt: null,
  trackingTier: null,
  coverageRatio: null,
};

function cloneIntervalSelection(interval: TimelineIntervalSelection | null) {
  return interval ? { ...interval } : null;
}

function cloneLprJobState(job: LprJobState) {
  return { ...job };
}

function cloneLprReviewState(review: LprReviewState | null) {
  return review ? {
    ...review,
    reasons: [...review.reasons],
  } : null;
}

function cloneLprAnalysisProvenance(provenance: LprAnalysisProvenance | null) {
  return provenance ? { ...provenance } : null;
}

function cloneLprDecisionTrace(decision: LprDecisionTrace | null) {
  return decision ? { ...decision } : null;
}

function cloneLprTargetTracks(targetTracks: LprTargetTrack[]) {
  return targetTracks.map((track) => ({
    ...track,
    frames: track.frames.map((frame) => ({
      ...frame,
      box: { ...frame.box },
    })),
  }));
}

function cloneLprTargetTrack(track: LprTargetTrack | null) {
  return track ? cloneLprTargetTracks([track])[0] ?? null : null;
}

function cloneLprTargetAnchor(anchor: LprTargetAnchor | null) {
  return anchor ? {
    ...anchor,
    box: { ...anchor.box },
  } : null;
}

function resolveAnchorFrame(
  track: Pick<LprTargetTrack, 'frames'>,
  preferredTimeMs: number | null | undefined,
) {
  if (track.frames.length === 0) {
    return null;
  }

  if (typeof preferredTimeMs !== 'number' || Number.isNaN(preferredTimeMs)) {
    return track.frames[0] ?? null;
  }

  return track.frames.reduce((closestFrame, candidateFrame) => (
    Math.abs(candidateFrame.timeMs - preferredTimeMs) < Math.abs(closestFrame.timeMs - preferredTimeMs)
      ? candidateFrame
      : closestFrame
  ));
}

export function buildLprTargetAnchor(
  track: Pick<LprTargetTrack, 'id' | 'className' | 'frames'> | null | undefined,
  preferredTimeMs?: number | null,
): LprTargetAnchor | null {
  if (!track) {
    return null;
  }

  const anchorFrame = resolveAnchorFrame(track, preferredTimeMs);
  if (!anchorFrame) {
    return null;
  }

  return {
    trackId: track.id,
    className: track.className,
    timeMs: anchorFrame.timeMs,
    box: { ...anchorFrame.box },
  };
}

function cloneLprPlateCandidates(candidates: LprPlateCandidate[]) {
  return candidates.map((candidate) => ({
    ...candidate,
    box: candidate.box ? { ...candidate.box } : null,
    quality: candidate.quality ? { ...candidate.quality } : null,
  }));
}

function cloneLprSamples(samples: LprFrameSample[]) {
  return samples.map((sample) => ({
    ...sample,
    targetBox: sample.targetBox ? { ...sample.targetBox } : null,
    plateBox: sample.plateBox ? { ...sample.plateBox } : null,
    quality: sample.quality ? { ...sample.quality } : null,
    selection: sample.selection ? { ...sample.selection, reasons: [...sample.selection.reasons] } : null,
    ocrInput: sample.ocrInput ? { ...sample.ocrInput } : null,
    temporalSupport: sample.temporalSupport ? { ...sample.temporalSupport, supportTimes: [...sample.temporalSupport.supportTimes] } : null,
    candidates: cloneLprPlateCandidates(sample.candidates),
  }));
}

function cloneLprHistory(history: LprResultHistoryEntry[]) {
  return history.map((entry) => ({
    ...entry,
    interval: cloneIntervalSelection(entry.interval),
    candidates: cloneLprPlateCandidates(entry.candidates),
  }));
}

export function resolveLprAnalysisTargetVehicleKind(
  selectedTargetTrack: Pick<LprTargetTrack, 'className'> | null | undefined,
  fallbackVehicleKind: LprVehicleKind,
): LprVehicleKind {
  switch (selectedTargetTrack?.className) {
    case 'car':
    case 'motorcycle':
    case 'truck':
    case 'bus':
      return selectedTargetTrack.className;
    default:
      return fallbackVehicleKind;
  }
}

export function buildDefaultLprState(overrides: Partial<LprSessionState> = {}): LprSessionState {
  return {
    workflowMode: overrides.workflowMode ?? 'idle',
    interval: cloneIntervalSelection(overrides.interval ?? null),
    selectedAnalysisProfileId: overrides.selectedAnalysisProfileId ?? defaultLprAnalysisProfileId,
    showDeveloperDiagnostics: overrides.showDeveloperDiagnostics ?? true,
    targetVehicleKind: overrides.targetVehicleKind ?? 'vehicle',
    useDenseSampling: overrides.useDenseSampling ?? true,
    countryHints: [...(overrides.countryHints ?? [])],
    job: cloneLprJobState(overrides.job ?? DEFAULT_LPR_JOB_STATE),
    targetTracks: cloneLprTargetTracks(overrides.targetTracks ?? []),
    selectedTargetTrackId: overrides.selectedTargetTrackId ?? null,
    selectedTargetAnchor: cloneLprTargetAnchor(overrides.selectedTargetAnchor ?? null),
    analysisTrack: cloneLprTargetTrack(overrides.analysisTrack ?? null),
    samples: cloneLprSamples(overrides.samples ?? []),
    candidates: cloneLprPlateCandidates(overrides.candidates ?? []),
    review: cloneLprReviewState(overrides.review ?? null),
    lastAnalysisProvenance: cloneLprAnalysisProvenance(overrides.lastAnalysisProvenance ?? null),
    decision: cloneLprDecisionTrace(overrides.decision ?? null),
    acceptedCandidateId: overrides.acceptedCandidateId ?? null,
    history: cloneLprHistory(overrides.history ?? []),
  };
}
