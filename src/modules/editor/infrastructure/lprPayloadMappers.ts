/**
 * IPC payload → frontend domain mappers (Blueprint §1.2 + §2.2, Phase 1-D).
 *
 * Specta bindings mark cross-process scalars as nullable (`number | null`),
 * while the frontend domain holds resolved values (NonNullable lift, Phase 1-A).
 * These pure functions bridge that gap explicitly with typed field mapping
 * (no assertions, no runtime validation — zod is Phase 2 scope).
 *
 * Null-resolution uses `??` fallbacks that only trigger on wire-nulls; every
 * real backend payload already carries concrete values, so behavior is
 * unchanged. Schemaless `diagnostics` payloads converge onto the single
 * domain-wide {@link Diagnostics} type.
 */
import type {
  AiEvidenceKeyframePayload,
  AiEvidenceOverlayBoxPayload,
  AiEvidenceResponsePayload,
  AiEvidenceSharedProjectionPayload,
  AiEvidenceTargetSelectionPayload,
  AiEvidenceTimelineFrameRefPayload,
  AiEvidenceToolCallPayload,
  LprAnalysisProvenancePayload,
  LprFrameSamplePayload,
  LprPlateCandidatePayload,
  LprQualityMetricsPayload,
  LprReviewStatePayload,
  LprTargetTrackPayload,
  LprTrackedRegionPayload,
  TimelineIntervalSelectionPayload,
  VideoMarkerRectPayload,
} from '../../../platform/ipc/bindings';
import type {
  AiEvidenceKeyframe,
  AiEvidenceOverlayBox,
  AiEvidenceResponse,
  AiEvidenceSharedProjection,
  AiEvidenceTargetSelection,
  AiEvidenceTimelineFrameRef,
  AiEvidenceToolCall,
} from '../domain/aiEvidenceState';
import type {
  LprAnalysisProvenance,
  LprFrameSample,
  LprPlateCandidate,
  LprQualityMetrics,
  LprReviewState,
  LprTargetTrack,
  LprTrackedRegion,
} from '../domain/lprState';
import type { TimelineIntervalSelection, VideoMarkerRect } from '../domain/model';

export function mapMarkerRectPayload(rect: VideoMarkerRectPayload): VideoMarkerRect {
  return {
    x: rect.x ?? 0,
    y: rect.y ?? 0,
    width: rect.width ?? 0,
    height: rect.height ?? 0,
  };
}

export function mapNullableMarkerRectPayload(rect: VideoMarkerRectPayload | null | undefined): VideoMarkerRect | null {
  return rect ? mapMarkerRectPayload(rect) : null;
}

export function mapIntervalSelectionPayload(
  interval: TimelineIntervalSelectionPayload | null | undefined,
): TimelineIntervalSelection | null {
  if (!interval) {
    return null;
  }
  return {
    startMs: interval.startMs ?? 0,
    endMs: interval.endMs ?? 0,
  };
}

export function mapQualityMetricsPayload(
  quality: LprQualityMetricsPayload | null | undefined,
): LprQualityMetrics | null {
  if (!quality) {
    return null;
  }
  return {
    sharpness: quality.sharpness ?? 0,
    contrast: quality.contrast ?? 0,
    plateArea: quality.plateArea ?? 0,
    angleScore: quality.angleScore ?? 0,
    occlusionScore: quality.occlusionScore ?? 0,
    glareScore: quality.glareScore ?? 0,
    legibilityScore: quality.legibilityScore ?? 0,
    overallScore: quality.overallScore ?? 0,
    legibilityLevel: quality.legibilityLevel,
  };
}

export function mapTrackedRegionPayload(region: LprTrackedRegionPayload): LprTrackedRegion {
  return {
    id: region.id,
    timeMs: region.timeMs ?? 0,
    box: mapMarkerRectPayload(region.box),
    confidence: region.confidence ?? 0,
    className: region.className,
    diagnostics: region.diagnostics,
  };
}

export function mapTargetTrackPayload(track: LprTargetTrackPayload): LprTargetTrack {
  return {
    id: track.id,
    className: track.className,
    label: track.label,
    confidence: track.confidence ?? 0,
    frames: track.frames.map(mapTrackedRegionPayload),
    diagnostics: track.diagnostics,
  };
}

export function mapNullableTargetTrackPayload(
  track: LprTargetTrackPayload | null | undefined,
): LprTargetTrack | null {
  return track ? mapTargetTrackPayload(track) : null;
}

export function mapPlateCandidatePayload(candidate: LprPlateCandidatePayload): LprPlateCandidate {
  return {
    id: candidate.id,
    text: candidate.text,
    confidence: candidate.confidence ?? 0,
    source: candidate.source,
    frameTimeMs: candidate.frameTimeMs,
    countryCode: candidate.countryCode,
    box: mapNullableMarkerRectPayload(candidate.box),
    quality: mapQualityMetricsPayload(candidate.quality),
    diagnostics: candidate.diagnostics,
  };
}

export function mapNullablePlateCandidatePayload(
  candidate: LprPlateCandidatePayload | null | undefined,
): LprPlateCandidate | null {
  return candidate ? mapPlateCandidatePayload(candidate) : null;
}

export function mapFrameSamplePayload(sample: LprFrameSamplePayload): LprFrameSample {
  return {
    id: sample.id,
    timeMs: sample.timeMs ?? 0,
    targetBox: mapNullableMarkerRectPayload(sample.targetBox),
    plateBox: mapNullableMarkerRectPayload(sample.plateBox),
    quality: mapQualityMetricsPayload(sample.quality),
    selection: sample.selection,
    ocrInput: sample.ocrInput,
    temporalSupport: sample.temporalSupport,
    diagnostics: sample.diagnostics,
    imagePath: sample.imagePath,
    candidates: sample.candidates.map(mapPlateCandidatePayload),
  };
}

export function mapNullableFrameSamplePayload(
  sample: LprFrameSamplePayload | null | undefined,
): LprFrameSample | null {
  return sample ? mapFrameSamplePayload(sample) : null;
}

export function mapReviewStatePayload(review: LprReviewStatePayload): LprReviewState {
  return {
    status: review.status,
    acceptedCandidateId: review.acceptedCandidateId,
    suggestedCandidateId: review.suggestedCandidateId,
    reasons: [...review.reasons],
  };
}

export function mapAnalysisProvenancePayload(provenance: LprAnalysisProvenancePayload): LprAnalysisProvenance {
  return {
    requestId: provenance.requestId,
    command: provenance.command,
    analysisProfileId: provenance.analysisProfileId,
    developerDiagnosticsEnabled: provenance.developerDiagnosticsEnabled,
    runtimeVersion: provenance.runtimeVersion,
    restorationMode: provenance.restorationMode,
    recognizerBackend: provenance.recognizerBackend,
    temporalEvidenceMode: provenance.temporalEvidenceMode,
    sequenceReviewMode: provenance.sequenceReviewMode,
    emittedAtMs: provenance.emittedAtMs ?? 0,
  };
}

export function mapAiEvidenceFrameRefPayload(
  frame: AiEvidenceTimelineFrameRefPayload,
): AiEvidenceTimelineFrameRef {
  return {
    frameId: frame.frameId,
    timeMs: frame.timeMs ?? 0,
    sequenceIndex: frame.sequenceIndex,
    label: frame.label,
    imagePath: frame.imagePath,
    frameWidth: frame.frameWidth,
    frameHeight: frame.frameHeight,
  };
}

export function mapNullableAiEvidenceFrameRefPayload(
  frame: AiEvidenceTimelineFrameRefPayload | null | undefined,
): AiEvidenceTimelineFrameRef | null {
  return frame ? mapAiEvidenceFrameRefPayload(frame) : null;
}

export function mapAiEvidenceOverlayBoxPayload(
  overlay: AiEvidenceOverlayBoxPayload | null | undefined,
): AiEvidenceOverlayBox | null {
  if (!overlay) {
    return null;
  }
  return {
    normalizedBox: mapNullableMarkerRectPayload(overlay.normalizedBox),
    pixelBox: overlay.pixelBox,
    frameWidth: overlay.frameWidth,
    frameHeight: overlay.frameHeight,
  };
}

export function mapAiEvidenceToolCallPayload(toolCall: AiEvidenceToolCallPayload): AiEvidenceToolCall {
  return {
    stage: toolCall.stage,
    toolName: toolCall.toolName,
    inputSummary: toolCall.inputSummary,
    outputSummary: toolCall.outputSummary,
    startedAtMs: toolCall.startedAtMs ?? 0,
    completedAtMs: toolCall.completedAtMs ?? 0,
    success: toolCall.success,
  };
}

export function mapAiEvidenceTargetSelectionPayload(
  selection: AiEvidenceTargetSelectionPayload | null | undefined,
): AiEvidenceTargetSelection | null {
  if (!selection) {
    return null;
  }
  return {
    anchorFrameId: selection.anchorFrameId,
    selectedTrackId: selection.selectedTrackId,
    selectedCandidateId: selection.selectedCandidateId,
    confidence: selection.confidence ?? 0,
    rationale: selection.rationale,
    selectedBox: mapAiEvidenceOverlayBoxPayload(selection.selectedBox),
  };
}

export function mapAiEvidenceKeyframePayload(keyframe: AiEvidenceKeyframePayload): AiEvidenceKeyframe {
  return {
    frame: mapAiEvidenceFrameRefPayload(keyframe.frame),
    description: keyframe.description,
    overlay: mapAiEvidenceOverlayBoxPayload(keyframe.overlay),
    selectedForTargetResolution: keyframe.selectedForTargetResolution,
    keyframeSource: keyframe.keyframeSource,
    descriptionSource: keyframe.descriptionSource,
    boxSource: keyframe.boxSource,
    isValidForUserFacingOutput: keyframe.isValidForUserFacingOutput,
  };
}

export function mapAiEvidenceSharedProjectionPayload(
  projection: AiEvidenceSharedProjectionPayload,
): AiEvidenceSharedProjection {
  return {
    interval: mapIntervalSelectionPayload(projection.interval),
    targetTracks: projection.targetTracks.map(mapTargetTrackPayload),
    analysisTrack: mapNullableTargetTrackPayload(projection.analysisTrack),
    selectedTargetTrackId: projection.selectedTargetTrackId,
    samples: projection.samples.map(mapFrameSamplePayload),
    candidates: projection.candidates.map(mapPlateCandidatePayload),
    acceptedCandidateId: projection.acceptedCandidateId,
    review: projection.review ? mapReviewStatePayload(projection.review) : null,
    provenance: projection.provenance ? mapAnalysisProvenancePayload(projection.provenance) : null,
    decision: projection.decision,
  };
}

export function mapAiEvidenceResponsePayload(response: AiEvidenceResponsePayload): AiEvidenceResponse {
  return {
    requestId: response.requestId,
    description: response.description,
    summary: response.summary,
    provider: response.provider,
    interval: mapIntervalSelectionPayload(response.interval),
    plateNumber: response.plateNumber,
    plateCandidate: mapNullablePlateCandidatePayload(response.plateCandidate),
    primaryAnchor: mapNullableAiEvidenceFrameRefPayload(response.primaryAnchor),
    targetSelection: mapAiEvidenceTargetSelectionPayload(response.targetSelection),
    keyframes: response.keyframes.map(mapAiEvidenceKeyframePayload),
    keyframeCountReason: response.keyframeCountReason,
    toolCalls: response.toolCalls.map(mapAiEvidenceToolCallPayload),
    projection: mapAiEvidenceSharedProjectionPayload(response.projection),
    clipPath: response.clipPath,
    runtime: response.runtime,
  };
}

// ---------------------------------------------------------------------------
// Domain → payload (request direction). Bindings mark diagnostics and several
// box/provenance fields as required-but-nullable, while the domain keeps them
// optional — these mappers resolve `undefined` to `null` explicitly.
// ---------------------------------------------------------------------------

export function toTrackedRegionPayload(region: LprTrackedRegion): LprTrackedRegionPayload {
  return {
    id: region.id,
    timeMs: region.timeMs,
    box: region.box,
    confidence: region.confidence,
    className: region.className,
    diagnostics: region.diagnostics ?? null,
  };
}

export function toTargetTrackPayload(track: LprTargetTrack): LprTargetTrackPayload {
  return {
    id: track.id,
    className: track.className,
    label: track.label,
    confidence: track.confidence,
    frames: track.frames.map(toTrackedRegionPayload),
    diagnostics: track.diagnostics ?? null,
  };
}

export function toPlateCandidatePayload(candidate: LprPlateCandidate): LprPlateCandidatePayload {
  return {
    id: candidate.id,
    text: candidate.text,
    confidence: candidate.confidence,
    source: candidate.source,
    frameTimeMs: candidate.frameTimeMs,
    countryCode: candidate.countryCode,
    box: candidate.box,
    quality: candidate.quality,
    diagnostics: candidate.diagnostics ?? null,
  };
}

export function toFrameSamplePayload(sample: LprFrameSample): LprFrameSamplePayload {
  return {
    id: sample.id,
    timeMs: sample.timeMs,
    targetBox: sample.targetBox ?? null,
    plateBox: sample.plateBox ?? null,
    quality: sample.quality ?? null,
    candidates: sample.candidates.map(toPlateCandidatePayload),
    imagePath: sample.imagePath ?? null,
    selection: sample.selection ?? null,
    ocrInput: sample.ocrInput ?? null,
    temporalSupport: sample.temporalSupport ?? null,
    diagnostics: sample.diagnostics ?? null,
  };
}

export function toAnalysisProvenancePayload(provenance: LprAnalysisProvenance): LprAnalysisProvenancePayload {
  return {
    requestId: provenance.requestId,
    command: provenance.command,
    analysisProfileId: provenance.analysisProfileId,
    developerDiagnosticsEnabled: provenance.developerDiagnosticsEnabled,
    runtimeVersion: provenance.runtimeVersion,
    restorationMode: provenance.restorationMode ?? null,
    recognizerBackend: provenance.recognizerBackend ?? null,
    temporalEvidenceMode: provenance.temporalEvidenceMode ?? null,
    sequenceReviewMode: provenance.sequenceReviewMode ?? null,
    emittedAtMs: provenance.emittedAtMs,
  };
}
