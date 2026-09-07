/**
 * AI evidence response boundary schemas (Blueprint §2.3, Phase 2-A).
 *
 * Same contract as `lprSchemas.ts`: parse exactly once in the infrastructure
 * layer, after {@link unwrapCommand} and before the typed mappers in
 * `lprPayloadMappers.ts` (signatures untouched). Shared LPR building blocks
 * (tracks, samples, candidates, review, provenance, decision) are reused from
 * `lprSchemas.ts` instead of being redeclared.
 *
 * Wire-nullable fields stay `.nullable()`; `??` convergence to domain
 * defaults remains the mappers' job. Failures throw {@link IpcCommandError}
 * with the command name plus a zod issue summary.
 */
import { z } from 'zod';
import type { AiEvidenceResponsePayload } from '../../../platform/ipc/bindings';
import { IpcCommandError } from '../../../platform/ipc/ipc-unwrap';
import {
  lprAnalysisProvenanceSchema,
  lprDecisionTraceSchema,
  lprFrameSampleSchema,
  lprPlateCandidateSchema,
  lprReviewStateSchema,
  lprRuntimeStatusSchema,
  lprTargetTrackSchema,
  timelineIntervalSelectionSchema,
  videoMarkerRectSchema,
} from './lprSchemas';

export const aiEvidencePixelBoxSchema = z.object({
  x: z.number(),
  y: z.number(),
  width: z.number(),
  height: z.number(),
});

export const aiEvidenceOverlayBoxSchema = z.object({
  normalizedBox: videoMarkerRectSchema.nullable(),
  pixelBox: aiEvidencePixelBoxSchema.nullable(),
  frameWidth: z.number(),
  frameHeight: z.number(),
});

export const aiEvidenceTimelineFrameRefSchema = z.object({
  frameId: z.string(),
  timeMs: z.number().nullable(),
  sequenceIndex: z.number(),
  label: z.string(),
  imagePath: z.string().nullable(),
  frameWidth: z.number(),
  frameHeight: z.number(),
});

export const aiEvidenceToolCallSchema = z.object({
  stage: z.string(),
  toolName: z.string(),
  inputSummary: z.string(),
  outputSummary: z.string(),
  startedAtMs: z.number().nullable(),
  completedAtMs: z.number().nullable(),
  success: z.boolean(),
});

export const aiEvidenceTargetSelectionSchema = z.object({
  anchorFrameId: z.string(),
  selectedTrackId: z.string().nullable(),
  selectedCandidateId: z.string().nullable(),
  confidence: z.number().nullable(),
  rationale: z.string(),
  selectedBox: aiEvidenceOverlayBoxSchema.nullable(),
});

export const aiEvidenceKeyframeSchema = z.object({
  frame: aiEvidenceTimelineFrameRefSchema,
  description: z.string(),
  overlay: aiEvidenceOverlayBoxSchema.nullable(),
  selectedForTargetResolution: z.boolean().nullable(),
  keyframeSource: z.string().nullable(),
  descriptionSource: z.string().nullable(),
  boxSource: z.string().nullable(),
  isValidForUserFacingOutput: z.boolean().nullable(),
});

export const aiEvidenceSharedProjectionSchema = z.object({
  interval: timelineIntervalSelectionSchema.nullable(),
  targetTracks: z.array(lprTargetTrackSchema),
  analysisTrack: lprTargetTrackSchema.nullable(),
  selectedTargetTrackId: z.string().nullable(),
  samples: z.array(lprFrameSampleSchema),
  candidates: z.array(lprPlateCandidateSchema),
  acceptedCandidateId: z.string().nullable(),
  review: lprReviewStateSchema.nullable(),
  provenance: lprAnalysisProvenanceSchema.nullable(),
  decision: lprDecisionTraceSchema.nullable(),
});

export const aiEvidenceResponseSchema = z.object({
  requestId: z.string().nullable(),
  description: z.string(),
  summary: z.string(),
  provider: z.enum(['mock', 'gemini', 'local']),
  interval: timelineIntervalSelectionSchema.nullable(),
  plateNumber: z.string().nullable(),
  plateCandidate: lprPlateCandidateSchema.nullable(),
  primaryAnchor: aiEvidenceTimelineFrameRefSchema.nullable(),
  targetSelection: aiEvidenceTargetSelectionSchema.nullable(),
  keyframes: z.array(aiEvidenceKeyframeSchema),
  keyframeCountReason: z.string().nullable(),
  toolCalls: z.array(aiEvidenceToolCallSchema),
  projection: aiEvidenceSharedProjectionSchema,
  clipPath: z.string().nullable(),
  runtime: lprRuntimeStatusSchema,
});

function toIssueSummary(error: z.ZodError): string {
  return error.issues.map((issue) => `${String(issue.path.join('.')) || '(root)'}: ${issue.message}`).join('; ');
}

export function parseAiEvidenceResponse(command: string, raw: unknown): AiEvidenceResponsePayload {
  const parsed = aiEvidenceResponseSchema.safeParse(raw);
  if (!parsed.success) {
    throw new IpcCommandError('command', command, `invalid response payload: ${toIssueSummary(parsed.error)}`);
  }
  return parsed.data;
}
