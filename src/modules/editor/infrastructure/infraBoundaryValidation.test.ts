/**
 * Infrastructure boundary-validation contract (Blueprint §2.3, Phase 2-A).
 *
 * Locks the behavior of `lprSchemas.ts` / `aiEvidenceSchemas.ts`: every
 * cross-process response must pass its zod schema before reaching the typed
 * mappers. Valid payloads (including wire-nullable fields) are accepted as
 * clean objects; malformed payloads throw a structured `IpcCommandError`
 * naming the command plus a zod issue summary.
 *
 * Contract-tightening note: malformed cross-process input previously flowed
 * into the mappers as undefined behavior (whatever the backend happened to
 * send). It now fails loudly with `IpcCommandError`, which is the intended
 * Phase 2 contract — not a behavior regression.
 */
import { describe, expect, it } from 'vitest';

import type {
  AiEvidenceResponsePayload,
  LprAnalysisProvenancePayload,
  LprFrameAnalysisResponsePayload,
  LprReviewStatePayload,
  LprRuntimeStatusPayload,
} from '../../../domain/ipc/bindings';
import { IpcCommandError } from '../../../infrastructure/ipc-unwrap';
import { parseAiEvidenceResponse } from './aiEvidenceSchemas';
import {
  parseLprCancelRuntimeJobResponse,
  parseLprFrameAnalysisResponse,
  parseLprRuntimeStatusResponse,
  parseLprTargetScanResponse,
} from './lprSchemas';

const runtime: LprRuntimeStatusPayload = {
  available: true,
  pythonExecutable: '/usr/bin/python3',
  runtimeScript: 'runtime.py',
  version: '1.0.0',
  missingPackages: [],
  installedPackages: ['numpy'],
  detail: 'ok',
};

const review: LprReviewStatePayload = {
  status: 'no-candidate',
  acceptedCandidateId: null,
  suggestedCandidateId: null,
  reasons: [],
};

const provenance: LprAnalysisProvenancePayload = {
  requestId: 'req-001',
  command: 'analyze_lpr_frame',
  analysisProfileId: null,
  developerDiagnosticsEnabled: false,
  runtimeVersion: null,
  restorationMode: null,
  recognizerBackend: null,
  temporalEvidenceMode: null,
  sequenceReviewMode: null,
  emittedAtMs: null,
};

function expectCommandError(fn: () => unknown, command: string): void {
  try {
    fn();
  } catch (error: unknown) {
    expect(error).toBeInstanceOf(IpcCommandError);
    const failure = error as IpcCommandError;
    expect(failure.command).toBe(command);
    expect(failure.message).toContain(command);
    return;
  }
  throw new Error(`expected IpcCommandError for ${command}`);
}

describe('lpr boundary schemas', () => {
  it('accepts a valid runtime status payload', () => {
    expect(parseLprRuntimeStatusResponse('get_lpr_runtime_status', runtime)).toEqual(runtime);
  });

  it('accepts a valid target-scan response with wire-nullable fields', () => {
    const raw = {
      detections: [
        {
          id: 'det-1',
          timeMs: null,
          box: { x: null, y: null, width: null, height: null },
          confidence: null,
          className: 'vehicle',
          diagnostics: null,
        },
      ],
      runtime,
    };
    const parsed = parseLprTargetScanResponse('scan_lpr_targets', raw);
    expect(parsed.detections).toHaveLength(1);
    expect(parsed.detections[0]?.timeMs).toBeNull();
  });

  it('accepts a valid frame-analysis response with schemaless diagnostics', () => {
    const raw: LprFrameAnalysisResponsePayload = {
      detections: [],
      sample: null,
      candidates: [],
      acceptedCandidateId: null,
      review: { ...review },
      provenance: { ...provenance },
      decision: null,
      runtime,
      jobStatus: null,
      diagnostics: { arbitrary: ['backend', 42] },
    };
    expect(parseLprFrameAnalysisResponse('analyze_lpr_frame', raw)).toEqual(raw);
  });

  it('accepts a boolean cancel response and rejects a non-boolean', () => {
    expect(parseLprCancelRuntimeJobResponse('cancel_lpr_runtime_job', true)).toBe(true);
    expectCommandError(() => parseLprCancelRuntimeJobResponse('cancel_lpr_runtime_job', 'yes'), 'cancel_lpr_runtime_job');
  });

  it('rejects a target-scan response with a wrong-typed field', () => {
    expectCommandError(
      () => parseLprTargetScanResponse('scan_lpr_targets', { detections: 'nope', runtime }),
      'scan_lpr_targets',
    );
  });

  it('rejects a runtime status missing a required field', () => {
    const { detail: _omitted, ...withoutDetail } = runtime;
    expect(_omitted).toBe('ok');
    expectCommandError(
      () => parseLprRuntimeStatusResponse('get_lpr_runtime_status', withoutDetail),
      'get_lpr_runtime_status',
    );
  });
});

describe('ai evidence boundary schemas', () => {
  it('accepts a minimal valid AI evidence response', () => {
    const raw: AiEvidenceResponsePayload = {
      requestId: null,
      description: 'white sedan',
      summary: 'found',
      provider: 'mock',
      interval: null,
      plateNumber: null,
      plateCandidate: null,
      primaryAnchor: null,
      targetSelection: null,
      keyframes: [],
      keyframeCountReason: null,
      toolCalls: [],
      projection: {
        interval: null,
        targetTracks: [],
        analysisTrack: null,
        selectedTargetTrackId: null,
        samples: [],
        candidates: [],
        acceptedCandidateId: null,
        review: null,
        provenance: null,
        decision: null,
      },
      clipPath: null,
      runtime,
    };
    expect(parseAiEvidenceResponse('analyze_ai_evidence', raw)).toEqual(raw);
  });

  it('rejects an AI evidence response with an unknown provider', () => {
    const raw = {
      requestId: null,
      description: 'white sedan',
      summary: 'found',
      provider: 'unknown-provider',
      interval: null,
      plateNumber: null,
      plateCandidate: null,
      primaryAnchor: null,
      targetSelection: null,
      keyframes: [],
      keyframeCountReason: null,
      toolCalls: [],
      projection: {
        interval: null,
        targetTracks: [],
        analysisTrack: null,
        selectedTargetTrackId: null,
        samples: [],
        candidates: [],
        acceptedCandidateId: null,
        review: null,
        provenance: null,
        decision: null,
      },
      clipPath: null,
      runtime,
    };
    expectCommandError(() => parseAiEvidenceResponse('analyze_ai_evidence', raw), 'analyze_ai_evidence');
  });
});
