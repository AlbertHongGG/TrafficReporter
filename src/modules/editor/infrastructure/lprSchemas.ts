/**
 * LPR response boundary schemas (Blueprint §2.3, Phase 2-A).
 *
 * Every payload arriving from outside the frontend process (Rust/Python via
 * Tauri IPC) is parsed here exactly once, in the infrastructure layer, after
 * {@link unwrapCommand} and before the typed mappers in
 * `lprPayloadMappers.ts` (whose function signatures are untouched). The
 * domain layer only ever receives the validated clean object.
 *
 * Shared conventions (kept in sync with the export/media-side agent):
 * - One schema file per API module; validation happens exactly once in infra.
 * - Wire-nullable fields stay `.nullable()` in the schema; `??` convergence
 *   to domain defaults remains the mappers' job.
 * - Schemaless `diagnostics` fields (Specta `any | null`) accept anything via
 *   `z.unknown()` and converge onto the domain-wide `Diagnostics` type.
 * - Failures throw {@link IpcCommandError} whose message carries the command
 *   name plus a zod issue summary.
 */
import { z } from 'zod';
import type {
  LprEvidenceExportResponsePayload,
  LprFrameAnalysisResponsePayload,
  LprIntervalAnalysisResponsePayload,
  LprRuntimeStatusPayload,
  LprTargetScanResponsePayload,
} from '../../../platform/ipc/bindings';
import { IpcCommandError } from '../../../platform/ipc/ipc-unwrap';

export const videoMarkerRectSchema = z.object({
  x: z.number().nullable(),
  y: z.number().nullable(),
  width: z.number().nullable(),
  height: z.number().nullable(),
});

export const timelineIntervalSelectionSchema = z.object({
  startMs: z.number().nullable(),
  endMs: z.number().nullable(),
});

export const lprRuntimeStatusSchema = z.object({
  available: z.boolean(),
  pythonExecutable: z.string().nullable(),
  runtimeScript: z.string().nullable(),
  version: z.string().nullable(),
  missingPackages: z.array(z.string()),
  installedPackages: z.array(z.string()),
  detail: z.string(),
});

export const lprQualityMetricsSchema = z.object({
  sharpness: z.number().nullable(),
  contrast: z.number().nullable(),
  plateArea: z.number().nullable(),
  angleScore: z.number().nullable(),
  occlusionScore: z.number().nullable(),
  glareScore: z.number().nullable(),
  legibilityScore: z.number().nullable(),
  overallScore: z.number().nullable(),
  legibilityLevel: z.enum(['perfect', 'good', 'poor', 'illegible', 'unknown']),
});

export const lprTrackedRegionSchema = z.object({
  id: z.string(),
  timeMs: z.number().nullable(),
  box: videoMarkerRectSchema,
  confidence: z.number().nullable(),
  className: z.string(),
  diagnostics: z.unknown(),
});

export const lprTargetTrackSchema = z.object({
  id: z.string(),
  className: z.string(),
  label: z.string(),
  confidence: z.number().nullable(),
  frames: z.array(lprTrackedRegionSchema),
  diagnostics: z.unknown(),
});

export const lprPlateCandidateSchema = z.object({
  id: z.string(),
  text: z.string(),
  confidence: z.number().nullable(),
  source: z.string(),
  frameTimeMs: z.number().nullable(),
  countryCode: z.string().nullable(),
  box: videoMarkerRectSchema.nullable(),
  quality: lprQualityMetricsSchema.nullable(),
  diagnostics: z.unknown(),
});

export const lprSampleSelectionSchema = z.object({
  selected: z.boolean(),
  priority: z.number().nullable(),
  reasons: z.array(
    z.enum([
      'anchor',
      'anchor-frame',
      'interval-start',
      'interval-end',
      'scheduled-sample',
      'temporal-burst',
      'motion-hotspot',
      'high-confidence',
      'highest-confidence',
      'highest-resolution',
      'representative',
      'temporal-support',
      'sharpness-peak',
    ]),
  ),
});

export const lprOcrInputSchema = z.object({
  stage: z.enum(['raw', 'original', 'rectified', 'enhanced', 'restored', 'temporal-restored', 'fused']),
  variant: z.string(),
  source: z.enum([
    'single-frame',
    'temporal-fusion',
    'cross-frame-vote',
    'user-selected',
    'fused-image',
    'fused-char',
    'temporal-restored',
    'support-carry',
    'legacy-vote',
  ]),
  imagePath: z.string().nullable(),
  supportFrameCount: z.number(),
});

export const lprTemporalSupportSchema = z.object({
  strategy: z.string(),
  referenceTimeMs: z.number().nullable(),
  supportFrameCount: z.number(),
  supportWindowMs: z.number().nullable(),
  supportTimes: z.array(z.number().nullable()),
  meanAlignmentScore: z.number().nullable(),
  meanQualityScore: z.number().nullable(),
  sourceStage: z.enum(['raw', 'original', 'rectified', 'enhanced', 'restored', 'temporal-restored', 'fused']),
  selectedStage: z.enum(['raw', 'original', 'rectified', 'enhanced', 'restored', 'temporal-restored', 'fused']),
});

export const lprFrameSampleSchema = z.object({
  id: z.string(),
  timeMs: z.number().nullable(),
  targetBox: videoMarkerRectSchema.nullable(),
  plateBox: videoMarkerRectSchema.nullable(),
  quality: lprQualityMetricsSchema.nullable(),
  candidates: z.array(lprPlateCandidateSchema),
  imagePath: z.string().nullable(),
  selection: lprSampleSelectionSchema.nullable(),
  ocrInput: lprOcrInputSchema.nullable(),
  temporalSupport: lprTemporalSupportSchema.nullable(),
  diagnostics: z.unknown(),
});

export const lprReviewStateSchema = z.object({
  status: z.enum(['accepted', 'review-required', 'no-candidate']),
  acceptedCandidateId: z.string().nullable(),
  suggestedCandidateId: z.string().nullable(),
  reasons: z.array(z.string()),
});

export const lprAnalysisProvenanceSchema = z.object({
  requestId: z.string().nullable(),
  command: z.string(),
  analysisProfileId: z.string().nullable(),
  developerDiagnosticsEnabled: z.boolean(),
  runtimeVersion: z.string().nullable(),
  restorationMode: z.string().nullable(),
  recognizerBackend: z.string().nullable(),
  temporalEvidenceMode: z.string().nullable(),
  sequenceReviewMode: z.string().nullable(),
  emittedAtMs: z.number().nullable(),
});

export const lprDecisionTraceSchema = z.object({
  source: z.enum([
    'single-frame',
    'temporal-fusion',
    'cross-frame-vote',
    'user-selected',
    'fused-image',
    'fused-char',
    'temporal-restored',
    'support-carry',
    'legacy-vote',
  ]),
  candidateId: z.string().nullable(),
  sampleId: z.string().nullable(),
  frameTimeMs: z.number().nullable(),
  stage: z.enum(['raw', 'original', 'rectified', 'enhanced', 'restored', 'temporal-restored', 'fused']).nullable(),
  supportFrameCount: z.number(),
  agreementRatio: z.number().nullable(),
  margin: z.number().nullable(),
});

const lprJobStatusSchema = z.enum(['idle', 'queued', 'running', 'completed', 'failed', 'cancelled', 'degraded']);

export const lprTrackingSummarySchema = z.object({
  trackingTier: z.enum(['full', 'partial', 'detection-fallback', 'anchor-only', 'anchor-invalid']),
  anchorStatus: z.enum([
    'valid',
    'missing-selection',
    'outside-interval',
    'not-detected',
    'mismatched',
    'degraded',
  ]),
  coverageRatio: z.number().nullable(),
  trackedFrameCount: z.number(),
  requestedFrameCount: z.number(),
  degradedReason: z.string().nullable(),
  terminatedEarly: z.boolean(),
});

export const lprSequenceSummarySchema = z.object({
  sequenceTier: z.enum(['stable', 'drifting', 'gapped', 'fragmented']),
  dominantText: z.string().nullable(),
  persistenceRatio: z.number().nullable(),
  supportFrameCount: z.number(),
  sampleCount: z.number(),
  supportFrameGapCount: z.number(),
  predictionSwitchCount: z.number(),
  characterConsistency: z.array(z.number().nullable()),
  characterConsistencyMean: z.number().nullable(),
});

export const lprTargetScanResponseSchema = z.object({
  detections: z.array(lprTrackedRegionSchema),
  runtime: lprRuntimeStatusSchema,
});

export const lprFrameAnalysisResponseSchema = z.object({
  detections: z.array(lprTrackedRegionSchema),
  sample: lprFrameSampleSchema.nullable(),
  candidates: z.array(lprPlateCandidateSchema),
  acceptedCandidateId: z.string().nullable(),
  review: lprReviewStateSchema,
  provenance: lprAnalysisProvenanceSchema,
  decision: lprDecisionTraceSchema.nullable(),
  runtime: lprRuntimeStatusSchema,
  jobStatus: lprJobStatusSchema.nullable(),
  diagnostics: z.unknown(),
});

export const lprIntervalAnalysisResponseSchema = z.object({
  targetTracks: z.array(lprTargetTrackSchema),
  analysisTrack: lprTargetTrackSchema.nullable(),
  samples: z.array(lprFrameSampleSchema),
  candidates: z.array(lprPlateCandidateSchema),
  acceptedCandidateId: z.string().nullable(),
  review: lprReviewStateSchema,
  provenance: lprAnalysisProvenanceSchema,
  decision: lprDecisionTraceSchema.nullable(),
  summary: z.string(),
  runtime: lprRuntimeStatusSchema,
  jobStatus: lprJobStatusSchema.nullable(),
  tracking: lprTrackingSummarySchema.nullable(),
  sequence: lprSequenceSummarySchema.nullable(),
  diagnostics: z.unknown(),
});

export const lprEvidenceExportResponseSchema = z.object({
  jsonPath: z.string(),
  imagePath: z.string(),
  bundleDir: z.string(),
  exportedFileCount: z.number(),
  decisionFrameCount: z.number(),
});

export const lprCancelRuntimeJobResponseSchema = z.boolean();

function toIssueSummary(error: z.ZodError): string {
  return error.issues.map((issue) => `${String(issue.path.join('.')) || '(root)'}: ${issue.message}`).join('; ');
}

function parseOrThrow<T>(command: string, schema: z.ZodType<T>, raw: unknown): T {
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new IpcCommandError('command', command, `invalid response payload: ${toIssueSummary(parsed.error)}`);
  }
  return parsed.data;
}

export function parseLprRuntimeStatusResponse(command: string, raw: unknown): LprRuntimeStatusPayload {
  return parseOrThrow(command, lprRuntimeStatusSchema, raw);
}

export function parseLprCancelRuntimeJobResponse(command: string, raw: unknown): boolean {
  return parseOrThrow(command, lprCancelRuntimeJobResponseSchema, raw);
}

export function parseLprTargetScanResponse(command: string, raw: unknown): LprTargetScanResponsePayload {
  return parseOrThrow(command, lprTargetScanResponseSchema, raw);
}

export function parseLprFrameAnalysisResponse(command: string, raw: unknown): LprFrameAnalysisResponsePayload {
  return parseOrThrow(command, lprFrameAnalysisResponseSchema, raw);
}

export function parseLprIntervalAnalysisResponse(command: string, raw: unknown): LprIntervalAnalysisResponsePayload {
  return parseOrThrow(command, lprIntervalAnalysisResponseSchema, raw);
}

export function parseLprEvidenceExportResponse(command: string, raw: unknown): LprEvidenceExportResponsePayload {
  return parseOrThrow(command, lprEvidenceExportResponseSchema, raw);
}
