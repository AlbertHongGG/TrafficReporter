import type {
  AiEvidenceProgressKind,
  AiEvidenceResponse,
  LprAnalysisOptionsPayload,
  LprAnalysisProfileId,
  LprAnalysisProvenance,
  LprDecisionTrace,
  LprFrameSample,
  LprJobStatus,
  LprPlateCandidate,
  LprReviewState,
  LprTargetTrack,
  LprTrackingTier,
  LprVehicleKind,
  LprWorkflowMode,
  MediaProbeResult,
  OutputCompressionMode,
  TimelineIntervalSelection,
  VideoMarkerRect,
} from './index';

export type MediaKind = 'video';

export interface MediaAssetRecord extends MediaProbeResult {
  id: string;
  name: string;
  path: string;
  kind: MediaKind;
}

export type OperationFeedbackScope = 'import' | 'workspace' | 'export' | 'playback';

export interface OperationFeedback {
  scope: OperationFeedbackScope;
  message: string;
}

export const DEFAULT_OUTPUT_COMPRESSION_MODE: OutputCompressionMode = 'standard';

export interface LprAnalysisProfileDefinition {
  id: LprAnalysisProfileId;
  label: string;
  description: string;
  options: LprAnalysisOptionsPayload;
}

export interface LprAnalysisProfileCatalog {
  version: number;
  defaultProfileId: LprAnalysisProfileId;
  developerDiagnosticsOptions?: LprAnalysisOptionsPayload | null;
  profiles: LprAnalysisProfileDefinition[];
}

export interface LprTargetAnchor {
  trackId: string;
  className: string;
  timeMs: number;
  box: VideoMarkerRect;
}

export interface LprJobState {
  status: LprJobStatus;
  progress: number;
  stage: string;
  detail: string;
  requestId: string | null;
  error: string | null;
  reasonCode?: string | null;
  startedAt: string | null;
  stageStartedAt: string | null;
  updatedAt: string | null;
  trackingTier?: LprTrackingTier | null;
  coverageRatio?: number | null;
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

export interface AiEvidenceJobState {
  status: LprJobStatus;
  progress: number;
  stage: string;
  detail: string;
  requestId: string | null;
  error: string | null;
  progressKind?: AiEvidenceProgressKind | null;
  toolName?: string | null;
  toolLabel?: string | null;
  stepIndex?: number | null;
  stepCount?: number | null;
  stageStepIndex?: number | null;
  stageStepCount?: number | null;
  startedAt: string | null;
  stageStartedAt: string | null;
  updatedAt: string | null;
}

export interface AiEvidenceSessionState {
  prompt: string;
  job: AiEvidenceJobState;
  result: AiEvidenceResponse | null;
  lastCompletedAt: string | null;
}
