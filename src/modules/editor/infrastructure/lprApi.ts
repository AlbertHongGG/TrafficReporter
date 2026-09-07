/**
 * LPR per-module infrastructure API (Blueprint §2.2, Phase 1-D).
 *
 * The only layer allowed to touch `bindings.commands`. Each function sends a
 * domain request (mapped to its payload shape), unwraps the Tauri result with
 * the shared {@link unwrapCommand} helper, then maps the payload back to the
 * frontend domain via typed field mapping (no assertions).
 */
import { commands } from '../../../domain/ipc/bindings';
import type {
  LprFrameAnalysisRequestPayload,
  LprIntervalAnalysisRequestPayload,
  LprTargetScanRequestPayload,
} from '../../../domain/ipc/bindings';
import { unwrapCommand } from '../../../infrastructure/ipc-unwrap';
import {
  parseLprCancelRuntimeJobResponse,
  parseLprEvidenceExportResponse,
  parseLprFrameAnalysisResponse,
  parseLprIntervalAnalysisResponse,
  parseLprRuntimeStatusResponse,
  parseLprTargetScanResponse,
} from './lprSchemas';
import type {
  LprEvidenceExportRequest,
  LprEvidenceExportResponse,
  LprFrameAnalysisRequest,
  LprFrameAnalysisResponse,
  LprIntervalAnalysisRequest,
  LprIntervalAnalysisResponse,
  LprRuntimeStatus,
  LprTargetScanRequest,
  LprTargetScanResponse,
} from '../domain/lprState';
import {
  mapAnalysisProvenancePayload,
  mapFrameSamplePayload,
  mapNullableFrameSamplePayload,
  mapNullableTargetTrackPayload,
  mapPlateCandidatePayload,
  mapReviewStatePayload,
  mapTargetTrackPayload,
  mapTrackedRegionPayload,
  toAnalysisProvenancePayload,
  toFrameSamplePayload,
  toPlateCandidatePayload,
  toTargetTrackPayload,
} from './lprPayloadMappers';

function toTargetScanRequestPayload(request: LprTargetScanRequest): LprTargetScanRequestPayload {
  return {
    sourcePath: request.sourcePath,
    timeMs: request.timeMs,
    markerRect: request.markerRect,
    targetVehicleKind: request.targetVehicleKind,
    requestId: request.requestId ?? null,
  };
}

function toFrameAnalysisRequestPayload(request: LprFrameAnalysisRequest): LprFrameAnalysisRequestPayload {
  return {
    sourcePath: request.sourcePath,
    timeMs: request.timeMs,
    markerRect: request.markerRect,
    targetVehicleKind: request.targetVehicleKind,
    selectedTargetBox: request.selectedTargetBox ?? null,
    countryHints: request.countryHints,
    analysisProfileId: request.analysisProfileId ?? null,
    enableDeveloperDiagnostics: request.enableDeveloperDiagnostics ?? null,
    analysisOptions: request.analysisOptions ?? null,
    requestId: request.requestId ?? null,
  };
}

function toIntervalAnalysisRequestPayload(request: LprIntervalAnalysisRequest): LprIntervalAnalysisRequestPayload {
  return {
    sourcePath: request.sourcePath,
    interval: request.interval,
    anchorTimeMs: request.anchorTimeMs,
    targetVehicleKind: request.targetVehicleKind,
    selectedTargetBox: request.selectedTargetBox ?? null,
    selectedTargetTrackId: request.selectedTargetTrackId ?? null,
    countryHints: request.countryHints,
    sampleEveryMs: request.sampleEveryMs ?? null,
    maxSamples: request.maxSamples ?? null,
    analysisIntent: request.analysisIntent ?? null,
    latencyBudgetMs: request.latencyBudgetMs ?? null,
    analysisProfileId: request.analysisProfileId ?? null,
    enableDeveloperDiagnostics: request.enableDeveloperDiagnostics ?? null,
    analysisOptions: request.analysisOptions ?? null,
    requestId: request.requestId ?? null,
  };
}

export async function getLprRuntimeStatus(): Promise<LprRuntimeStatus> {
  const raw = await unwrapCommand(commands.getLprRuntimeStatus(), 'get_lpr_runtime_status');
  return parseLprRuntimeStatusResponse('get_lpr_runtime_status', raw);
}

export async function cancelLprRuntimeJob(): Promise<boolean> {
  const raw = await unwrapCommand(commands.cancelLprRuntimeJob(), 'cancel_lpr_runtime_job');
  return parseLprCancelRuntimeJobResponse('cancel_lpr_runtime_job', raw);
}

export async function scanLprTargets(request: LprTargetScanRequest): Promise<LprTargetScanResponse> {
  const raw = await unwrapCommand(
    commands.scanLprTargets(toTargetScanRequestPayload(request)),
    'scan_lpr_targets',
  );
  const response = parseLprTargetScanResponse('scan_lpr_targets', raw);
  return {
    detections: response.detections.map(mapTrackedRegionPayload),
    runtime: response.runtime,
  };
}

export async function analyzeLprFrame(request: LprFrameAnalysisRequest): Promise<LprFrameAnalysisResponse> {
  const raw = await unwrapCommand(
    commands.analyzeLprFrame(toFrameAnalysisRequestPayload(request)),
    'analyze_lpr_frame',
  );
  const response = parseLprFrameAnalysisResponse('analyze_lpr_frame', raw);
  return {
    detections: response.detections.map(mapTrackedRegionPayload),
    sample: mapNullableFrameSamplePayload(response.sample),
    candidates: response.candidates.map(mapPlateCandidatePayload),
    acceptedCandidateId: response.acceptedCandidateId,
    review: mapReviewStatePayload(response.review),
    provenance: mapAnalysisProvenancePayload(response.provenance),
    decision: response.decision,
    runtime: response.runtime,
    jobStatus: response.jobStatus,
    diagnostics: response.diagnostics,
  };
}

export async function analyzeLprInterval(request: LprIntervalAnalysisRequest): Promise<LprIntervalAnalysisResponse> {
  const raw = await unwrapCommand(
    commands.analyzeLprInterval(toIntervalAnalysisRequestPayload(request)),
    'analyze_lpr_interval',
  );
  const response = parseLprIntervalAnalysisResponse('analyze_lpr_interval', raw);
  return {
    targetTracks: response.targetTracks.map(mapTargetTrackPayload),
    analysisTrack: mapNullableTargetTrackPayload(response.analysisTrack),
    samples: response.samples.map(mapFrameSamplePayload),
    candidates: response.candidates.map(mapPlateCandidatePayload),
    acceptedCandidateId: response.acceptedCandidateId,
    review: mapReviewStatePayload(response.review),
    provenance: mapAnalysisProvenancePayload(response.provenance),
    decision: response.decision,
    summary: response.summary,
    runtime: response.runtime,
    jobStatus: response.jobStatus,
    tracking: response.tracking,
    sequence: response.sequence,
    diagnostics: response.diagnostics,
  };
}

export async function exportLprEvidence(request: LprEvidenceExportRequest): Promise<LprEvidenceExportResponse> {
  const raw = await unwrapCommand(
    commands.exportLprEvidence({
      outputPath: request.outputPath,
      sourcePath: request.sourcePath,
      timeMs: request.timeMs,
      markerRect: request.markerRect,
      compressionMode: request.compressionMode,
      interval: request.interval ?? null,
      targetTrack: request.targetTrack ? toTargetTrackPayload(request.targetTrack) : null,
      acceptedCandidate: request.acceptedCandidate ? toPlateCandidatePayload(request.acceptedCandidate) : null,
      candidates: request.candidates.map(toPlateCandidatePayload),
      samples: request.samples.map(toFrameSamplePayload),
      review: request.review ?? null,
      provenance: request.provenance ? toAnalysisProvenancePayload(request.provenance) : null,
    }),
    'export_lpr_evidence',
  );
  const response = parseLprEvidenceExportResponse('export_lpr_evidence', raw);
  return {
    jsonPath: response.jsonPath,
    imagePath: response.imagePath,
    bundleDir: response.bundleDir,
    exportedFileCount: response.exportedFileCount,
    decisionFrameCount: response.decisionFrameCount,
  };
}
