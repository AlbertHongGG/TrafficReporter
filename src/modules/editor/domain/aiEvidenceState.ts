import type {
  AiEvidenceProviderKind,
  LprDecisionTrace,
  LprJobStatus,
  LprVehicleKind,
} from '../../../types/bindings';
import type { TimelineIntervalSelection, VideoMarkerRect } from './model';
import type { OutputCompressionMode } from '../../export/domain/model';
import type { LprAnalysisProfileId } from './lprProfiles';
import type {
  LprAnalysisProvenance,
  LprFrameSample,
  LprPlateCandidate,
  LprReviewState,
  LprRuntimeStatus,
  LprTargetTrack,
} from './lprState';

export type AiEvidenceProgressKind = 'host-step' | 'tool-call';

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

const cloneSerializable = <T,>(value: T): T => {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
};

export const DEFAULT_AI_EVIDENCE_JOB_STATE: AiEvidenceJobState = {
  status: 'idle',
  progress: 0,
  stage: '',
  detail: '',
  requestId: null,
  error: null,
  startedAt: null,
  stageStartedAt: null,
  updatedAt: null,
  progressKind: null,
  toolName: null,
  toolLabel: null,
  stepIndex: null,
  stepCount: null,
  stageStepIndex: null,
  stageStepCount: null,
};

function cloneAiEvidenceResult(result: AiEvidenceResponse | null) {
  return result ? cloneSerializable(result) : null;
}

export function buildDefaultAiEvidenceState(overrides: Partial<AiEvidenceSessionState> = {}): AiEvidenceSessionState {
  return {
    prompt: overrides.prompt ?? '',
    job: {
      ...DEFAULT_AI_EVIDENCE_JOB_STATE,
      ...(overrides.job ? cloneSerializable(overrides.job) : {}),
    },
    result: cloneAiEvidenceResult(overrides.result ?? null),
    lastCompletedAt: overrides.lastCompletedAt ?? null,
  };
}