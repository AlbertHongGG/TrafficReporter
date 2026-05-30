// This file is auto-generated from schemas/lpr/lpr-contracts.json.
// Do not edit manually.

import type { OutputCompressionMode } from './editor';
import type { VideoMarkerRect } from './editor';

export type LprWorkflowMode = 'idle' | 'range' | 'target' | 'review';

export type LprJobStatus = 'idle' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'degraded';

export type LprTrackingTier = 'full' | 'partial' | 'detection-fallback' | 'anchor-only' | 'anchor-invalid';

export type LprAnchorStatus = 'valid' | 'missing-selection' | 'outside-interval' | 'not-detected' | 'mismatched' | 'degraded';

export type LprVehicleKind = 'any' | 'vehicle' | 'motorcycle' | 'car' | 'truck' | 'bus';

export type LprLegibilityLevel = 'perfect' | 'good' | 'poor' | 'illegible' | 'unknown';

export type LprAnalysisProfileId = string;

export type LprAnalysisIntent = 'interactive-short-range' | 'interactive-range' | 'interactive-dense-range' | 'ai-evidence-range' | 'benchmark-case';

export type LprRecognitionSource = 'baseline' | 'fused' | 'legacy-vote' | 'fused-char' | `ocr:${string}` | `fused-image:${string}`;

export type LprDiagnostics = Record<string, unknown>;

export type LprArtifactStage = 'original' | 'rectified' | 'enhanced' | 'restored' | 'temporal-restored' | 'working';

export type LprEvidenceReason = 'interval-start' | 'interval-end' | 'anchor' | 'scheduled-sample' | 'motion-hotspot' | 'high-confidence' | 'sharpness-peak' | 'temporal-burst';

export type LprDecisionSource = 'single-frame' | 'temporal-restored' | 'fused-image' | 'fused-char' | 'legacy-vote' | 'support-carry';

export interface LprSampleSelection {
  selected: boolean;
  priority: number;
  reasons: LprEvidenceReason[];
}

export interface LprTemporalSupport {
  strategy: string;
  referenceTimeMs: number;
  supportFrameCount: number;
  supportWindowMs: number;
  supportTimes: number[];
  meanAlignmentScore: number;
  meanQualityScore: number;
  sourceStage: LprArtifactStage;
  selectedStage: LprArtifactStage;
}

export interface LprOcrInput {
  stage: LprArtifactStage;
  variant: string;
  source: LprDecisionSource;
  imagePath: string | null;
  supportFrameCount: number;
}

export interface LprDecisionTrace {
  source: LprDecisionSource;
  candidateId: string | null;
  sampleId: string | null;
  frameTimeMs: number | null;
  stage: LprArtifactStage | null;
  supportFrameCount: number;
  agreementRatio: number | null;
  margin: number | null;
}

export interface LprAnalysisOptions {
  persistArtifacts?: boolean;
  artifactDir?: string | null;
  trackerMode?: string;
  fusionMode?: string;
  restorationMode?: string;
  recognizerBackend?: string;
  temporalEvidenceMode?: string;
  sequenceReviewMode?: string;
  enableRectification?: boolean;
  enableEnhancement?: boolean;
  enableRecognizerComparison?: boolean;
  debugTag?: string | null;
  ocrModelNames?: string[];
  maxPlateCandidates?: number;
  trackerHighConfidence?: number;
  trackerLowConfidence?: number;
  maxTrackingGap?: number;
  minAlignmentScore?: number;
  enableReliabilityGates?: boolean;
  minAcceptedConfidence?: number;
  minCandidateMargin?: number;
  minIntervalSupportFrames?: number;
  minSequencePersistence?: number;
  maxSequenceGapCount?: number;
  temporalWindowMs?: number;
  temporalNeighborCount?: number;
  maxEvidenceSampleCount?: number;
  anchorBurstCount?: number;
}

export interface LprAnalysisProfileDefinition {
  id: LprAnalysisProfileId;
  label: string;
  description: string;
  options: LprAnalysisOptions;
}

export interface LprAnalysisProfileCatalog {
  version: number;
  defaultProfileId: LprAnalysisProfileId;
  developerDiagnosticsOptions?: LprAnalysisOptions | null;
  profiles: LprAnalysisProfileDefinition[];
}

export type LprReviewStatus = 'accepted' | 'review-required' | 'no-candidate';

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

export interface TimelineIntervalSelection {
  startMs: number;
  endMs: number;
}

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
  diagnostics?: LprDiagnostics | null;
}

export interface LprTargetTrack {
  id: string;
  className: string;
  label: string;
  confidence: number;
  frames: LprTrackedRegion[];
  diagnostics?: LprDiagnostics | null;
}

export interface LprTargetAnchor {
  trackId: string;
  className: string;
  timeMs: number;
  box: VideoMarkerRect;
}

export interface LprPlateCandidate {
  id: string;
  text: string;
  confidence: number;
  source: LprRecognitionSource;
  frameTimeMs: number | null;
  countryCode: string | null;
  box: VideoMarkerRect | null;
  quality: LprQualityMetrics | null;
  diagnostics?: LprDiagnostics | null;
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
  diagnostics?: LprDiagnostics | null;
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

export interface LprProgress {
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

export interface LprTrackingSummary {
  trackingTier: LprTrackingTier;
  anchorStatus: LprAnchorStatus;
  coverageRatio: number;
  trackedFrameCount: number;
  requestedFrameCount: number;
  degradedReason: string | null;
  terminatedEarly: boolean;
}

export type LprSequenceTier = 'stable' | 'drifting' | 'gapped' | 'fragmented';

export interface LprSequenceSummary {
  sequenceTier: LprSequenceTier;
  dominantText: string | null;
  persistenceRatio: number;
  supportFrameCount: number;
  sampleCount: number;
  supportFrameGapCount: number;
  predictionSwitchCount: number;
  characterConsistency: number[];
  characterConsistencyMean: number;
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
  selectedTargetBox: VideoMarkerRect | null;
  countryHints: string[];
  analysisProfileId?: LprAnalysisProfileId | null;
  enableDeveloperDiagnostics?: boolean;
  analysisOptions?: LprAnalysisOptions | null;
  requestId?: string | null;
}

export interface LprFrameAnalysisResponse {
  detections: LprTrackedRegion[];
  sample: LprFrameSample | null;
  candidates: LprPlateCandidate[];
  acceptedCandidateId: string | null;
  review: LprReviewState;
  provenance: LprAnalysisProvenance;
  decision?: LprDecisionTrace | null;
  runtime: LprRuntimeStatus;
  jobStatus?: LprJobStatus;
  diagnostics?: LprDiagnostics | null;
}

export interface LprIntervalAnalysisRequest {
  sourcePath: string;
  interval: TimelineIntervalSelection;
  anchorTimeMs: number;
  targetVehicleKind: LprVehicleKind;
  selectedTargetBox: VideoMarkerRect | null;
  selectedTargetTrackId?: string | null;
  countryHints: string[];
  sampleEveryMs?: number;
  maxSamples?: number;
  analysisIntent?: LprAnalysisIntent;
  latencyBudgetMs?: number;
  analysisProfileId?: LprAnalysisProfileId | null;
  enableDeveloperDiagnostics?: boolean;
  analysisOptions?: LprAnalysisOptions | null;
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
  decision?: LprDecisionTrace | null;
  summary: string;
  runtime: LprRuntimeStatus;
  jobStatus?: LprJobStatus;
  tracking?: LprTrackingSummary | null;
  sequence?: LprSequenceSummary | null;
  diagnostics?: LprDiagnostics | null;
}

export interface LprEvidenceExportRequest {
  outputPath: string;
  sourcePath: string;
  timeMs: number;
  markerRect: VideoMarkerRect | null;
  compressionMode: OutputCompressionMode;
  interval: TimelineIntervalSelection | null;
  targetTrack: LprTargetTrack | null;
  acceptedCandidate: LprPlateCandidate | null;
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

export type AiEvidenceProviderKind = 'ollama';

export interface AiEvidenceJobState {
  status: LprJobStatus;
  progress: number;
  stage: string;
  detail: string;
  requestId: string | null;
  error: string | null;
  startedAt: string | null;
  stageStartedAt: string | null;
  updatedAt: string | null;
  currentToolName?: string | null;
}

export interface AiEvidenceProgress {
  progress: number;
  stage: string;
  detail: string;
  done: boolean;
  failed: boolean;
  requestId: string | null;
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
  selectedForTargetResolution?: boolean;
  keyframeSource?: string;
  descriptionSource?: string;
  boxSource?: string;
  isValidForUserFacingOutput?: boolean;
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
  audioBitrateKbps?: number;
  targetVehicleKind: LprVehicleKind;
  countryHints: string[];
  analysisProfileId?: LprAnalysisProfileId | null;
  enableDeveloperDiagnostics?: boolean;
  coarseSampleEveryMs?: number;
  fineSampleEveryMs?: number;
  fineWindowPaddingMs?: number;
  maxKeyframes?: number;
  requestId?: string | null;
}

export interface AiEvidenceSessionState {
  prompt: string;
  job: AiEvidenceJobState;
  result: AiEvidenceResponse | null;
  lastCompletedAt: string | null;
}
