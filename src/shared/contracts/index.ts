// Single Source of Truth (SSOT) from Tauri Specta Bindings
export * from '../../types/bindings';

// Frontend Session and UI Domain Entities
export * from './session';

import type {
  AiEvidenceProviderKind,
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
  OutputCompressionModePayload,
} from '../../types/bindings';

export type AiEvidenceProgressKind = 'host-step' | 'tool-call';

// Domain Core Types (strongly typed numbers for UI calculation and editing)
export interface VideoMarkerRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TimelineIntervalSelection {
  startMs: number;
  endMs: number;
}

export interface TimelineClip {
  id: string;
  assetId: string;
  trackId: string;
  startMs: number;
  inPointMs: number;
  outPointMs: number;
  muted: boolean;
}

export interface TimelineTrack {
  id: string;
  name: string;
  order: number;
}

export interface MediaProbeResult {
  durationMs: number;
  hasVideo: boolean;
  hasAudio: boolean;
  fps?: number;
  audioBitrateKbps?: number;
  width?: number;
  height?: number;
}

export type ExportFormat = 'mp4' | 'mkv';
export type VideoQuality = 'source' | '2160p' | '1440p' | '1080p' | '720p' | '480p';
export type AudioBitrateKbps = 320 | 256 | 192 | 128 | 96;

export interface RenderProfile {
  format: ExportFormat;
  fps: number;
  videoQuality?: VideoQuality;
  audioBitrateKbps?: AudioBitrateKbps;
  compressionMode: OutputCompressionModePayload;
}
export type OutputCompressionMode = OutputCompressionModePayload;

export type ExportSource = {
  id: string;
  name: string;
  path: string;
  hasVideo: boolean;
  hasAudio: boolean;
  width?: number;
  height?: number;
};

export type ExportTrack = Pick<TimelineTrack, 'id' | 'name' | 'order'>;
export type ExportClip = Pick<
  TimelineClip,
  'id' | 'assetId' | 'trackId' | 'startMs' | 'inPointMs' | 'outPointMs' | 'muted'
>;

export interface ExportSnapshot {
  fileId: string;
  fileName: string;
  workspaceName: string;
  suggestedName: string;
  timelineDurationMs: number;
  hasVideo: boolean;
  hasAudio: boolean;
  dominantWidth?: number;
  dominantHeight?: number;
  sources: ExportSource[];
  tracks: ExportTrack[];
  clips: ExportClip[];
  renderProfile: RenderProfile;
}

export interface TimelineExportRequest {
  outputPath: string;
  profile: RenderProfile;
  snapshot: ExportSnapshot;
}

export interface FrameExportRequest {
  outputPath: string;
  sourcePath: string;
  timeMs: number;
  markerRect: VideoMarkerRect | null;
  compressionMode: OutputCompressionMode;
}

export interface ExportProgressPayload {
  progress: number;
  stage: string;
  detail: string;
  done: boolean;
  failed: boolean;
}

export type LprWorkflowMode = 'idle' | 'range' | 'target' | 'review';
export type LprAnalysisProfileId = string;

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
  diagnostics?: any | null;
}

export interface LprTargetTrack {
  id: string;
  className: string;
  label: string;
  confidence: number;
  frames: LprTrackedRegion[];
  diagnostics?: any | null;
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
  diagnostics?: any | null;
}

export interface LprFrameSample {
  id: string;
  timeMs: number;
  targetBox: VideoMarkerRect | null;
  plateBox: VideoMarkerRect | null;
  quality: LprQualityMetrics | null;
  candidates: LprPlateCandidate[];
  imagePath: string | null;
  selection?: LprSampleSelection | null;
  ocrInput?: LprOcrInput | null;
  temporalSupport?: LprTemporalSupport | null;
  diagnostics?: any | null;
}

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

export interface AiEvidenceProgressPayload {
  progress: number;
  stage: string;
  detail: string;
  progressKind?: AiEvidenceProgressKind | null;
  toolName?: string | null;
  toolLabel?: string | null;
  stepIndex?: number | null;
  stepCount?: number | null;
  stageStepIndex?: number | null;
  stageStepCount?: number | null;
  done: boolean;
  failed: boolean;
  requestId?: string | null;
}
export type AiEvidenceProgress = AiEvidenceProgressPayload;

export interface LprRuntimeStatus {
  available: boolean;
  pythonExecutable: string | null;
  runtimeScript: string | null;
  version: string | null;
  missingPackages: string[];
  installedPackages: string[];
  detail: string;
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
  diagnostics?: any | null;
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
  tracking: LprTrackingSummary | null;
  sequence: LprSequenceSummary | null;
  diagnostics?: any | null;
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

export interface AiEvidencePixelBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AiEvidenceOverlayBox {
  normalizedBox: VideoMarkerRect | null;
  pixelBox: AiEvidencePixelBox | null;
  frameWidth: number;
  frameHeight: number;
}

export interface AiEvidenceTimelineFrameRef {
  frameId: string;
  timeMs: number;
  sequenceIndex: number;
  label: string;
  imagePath: string | null;
  frameWidth: number;
  frameHeight: number;
}

export interface AiEvidenceToolCall {
  stage: string;
  toolName: string;
  inputSummary: string;
  outputSummary: string;
  startedAtMs: number;
  completedAtMs: number;
  success: boolean;
}

export interface AiEvidenceTargetSelection {
  anchorFrameId: string;
  selectedTrackId: string | null;
  selectedCandidateId: string | null;
  confidence: number;
  rationale: string;
  selectedBox: AiEvidenceOverlayBox | null;
}

export interface AiEvidenceKeyframe {
  frame: AiEvidenceTimelineFrameRef;
  description: string;
  overlay: AiEvidenceOverlayBox | null;
  selectedForTargetResolution?: boolean | null;
  keyframeSource?: string | null;
  descriptionSource?: string | null;
  boxSource?: string | null;
  isValidForUserFacingOutput?: boolean | null;
}

export interface AiEvidenceSharedProjection {
  interval: TimelineIntervalSelection | null;
  targetTracks: LprTargetTrack[];
  analysisTrack: LprTargetTrack | null;
  selectedTargetTrackId: string | null;
  samples: LprFrameSample[];
  candidates: LprPlateCandidate[];
  acceptedCandidateId: string | null;
  review: LprReviewState | null;
  provenance: LprAnalysisProvenance | null;
  decision: LprDecisionTrace | null;
}

export interface AiEvidenceResponse {
  requestId: string | null;
  description: string;
  summary: string;
  provider: AiEvidenceProviderKind;
  interval: TimelineIntervalSelection | null;
  plateNumber: string | null;
  plateCandidate: LprPlateCandidate | null;
  primaryAnchor: AiEvidenceTimelineFrameRef | null;
  targetSelection: AiEvidenceTargetSelection | null;
  keyframes: AiEvidenceKeyframe[];
  keyframeCountReason?: string | null;
  toolCalls: AiEvidenceToolCall[];
  projection: AiEvidenceSharedProjection;
  clipPath?: string | null;
  runtime: LprRuntimeStatus;
}

export interface AiEvidenceRequest {
  sourcePath: string;
  description: string;
  markerRect: VideoMarkerRect | null;
  compressionMode: OutputCompressionMode;
  audioBitrateKbps?: number | null;
  targetVehicleKind: LprVehicleKind;
  countryHints: string[];
  analysisProfileId?: LprAnalysisProfileId | null;
  enableDeveloperDiagnostics?: boolean | null;
  coarseSampleEveryMs?: number | null;
  fineSampleEveryMs?: number | null;
  fineWindowPaddingMs?: number | null;
  maxKeyframes?: number | null;
  requestId?: string | null;
}