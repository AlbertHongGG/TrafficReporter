import type { VideoMarkerRect } from './editor';

export type LprWorkflowMode = 'idle' | 'range' | 'target' | 'review';

export type LprJobStatus = 'idle' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type LprVehicleKind = 'any' | 'vehicle' | 'motorcycle' | 'car' | 'truck' | 'bus';

export type LprRecognitionSource = 'baseline' | 'fused' | 'legacy-vote' | 'fused-char' | `ocr:${string}` | `fused-image:${string}`;

export type LprLegibilityLevel = 'perfect' | 'good' | 'poor' | 'illegible' | 'unknown';

export type LprDiagnostics = Record<string, unknown>;

export interface LprAnalysisOptions {
  persistArtifacts?: boolean;
  artifactDir?: string | null;
  trackerMode?: 'legacy' | 'target-cascade' | 'bytetrack' | 'botsort' | string;
  fusionMode?: 'legacy' | 'aligned-char' | string;
  restorationMode?: 'off' | 'gated' | 'mambairv2' | 'mambairv2-x2' | 'mambairv2-x4' | string;
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
  diagnostics?: LprDiagnostics | null;
}

export interface LprJobState {
  status: LprJobStatus;
  progress: number;
  stage: string;
  detail: string;
  requestId: string | null;
  error: string | null;
  startedAt: string | null;
  updatedAt: string | null;
}

export interface LprResultHistoryEntry {
  id: string;
  createdAt: string;
  interval: TimelineIntervalSelection | null;
  targetTrackId: string | null;
  acceptedCandidateId: string | null;
  candidates: LprPlateCandidate[];
  summary: string;
}

export interface LprSessionState {
  workflowMode: LprWorkflowMode;
  interval: TimelineIntervalSelection | null;
  targetVehicleKind: LprVehicleKind;
  useDenseSampling: boolean;
  countryHints: string[];
  job: LprJobState;
  targetTracks: LprTargetTrack[];
  selectedTargetTrackId: string | null;
  samples: LprFrameSample[];
  candidates: LprPlateCandidate[];
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
  analysisOptions?: LprAnalysisOptions | null;
}

export interface LprFrameAnalysisResponse {
  detections: LprTrackedRegion[];
  sample: LprFrameSample | null;
  candidates: LprPlateCandidate[];
  acceptedCandidateId: string | null;
  runtime: LprRuntimeStatus;
  diagnostics?: LprDiagnostics | null;
}

export interface LprIntervalAnalysisRequest {
  sourcePath: string;
  interval: TimelineIntervalSelection;
  anchorTimeMs: number;
  targetVehicleKind: LprVehicleKind;
  selectedTargetBox: VideoMarkerRect | null;
  countryHints: string[];
  sampleEveryMs?: number;
  maxSamples?: number;
  analysisOptions?: LprAnalysisOptions | null;
}

export interface LprIntervalAnalysisResponse {
  targetTracks: LprTargetTrack[];
  samples: LprFrameSample[];
  candidates: LprPlateCandidate[];
  acceptedCandidateId: string | null;
  summary: string;
  runtime: LprRuntimeStatus;
  diagnostics?: LprDiagnostics | null;
}

export interface LprEvidenceExportRequest {
  outputPath: string;
  sourcePath: string;
  timeMs: number;
  markerRect: VideoMarkerRect | null;
  interval: TimelineIntervalSelection | null;
  targetTrack: LprTargetTrack | null;
  acceptedCandidate: LprPlateCandidate | null;
  candidates: LprPlateCandidate[];
  samples: LprFrameSample[];
}

export interface LprEvidenceExportResponse {
  jsonPath: string;
  imagePath: string;
  bundleDir: string;
  exportedFileCount: number;
  decisionFrameCount: number;
}