/**
 * AI evidence per-module infrastructure API (Blueprint §2.2, Phase 1-D).
 *
 * The only layer allowed to touch `bindings.commands` for AI evidence.
 * Request mapping + {@link unwrapCommand} + response mapping with typed fields.
 */
import { commands } from '../../../types/bindings';
import type { AiEvidenceRequestPayload } from '../../../types/bindings';
import { unwrapCommand } from '../../../infrastructure/ipc-unwrap';
import type { AiEvidenceRequest, AiEvidenceResponse } from '../domain/aiEvidenceState';
import { mapAiEvidenceResponsePayload } from './lprPayloadMappers';

function toAiEvidenceRequestPayload(request: AiEvidenceRequest): AiEvidenceRequestPayload {
  return {
    sourcePath: request.sourcePath,
    description: request.description,
    markerRect: request.markerRect,
    compressionMode: request.compressionMode,
    audioBitrateKbps: request.audioBitrateKbps ?? null,
    targetVehicleKind: request.targetVehicleKind,
    countryHints: request.countryHints,
    analysisProfileId: request.analysisProfileId ?? null,
    enableDeveloperDiagnostics: request.enableDeveloperDiagnostics ?? null,
    coarseSampleEveryMs: request.coarseSampleEveryMs ?? null,
    fineSampleEveryMs: request.fineSampleEveryMs ?? null,
    fineWindowPaddingMs: request.fineWindowPaddingMs ?? null,
    maxKeyframes: request.maxKeyframes ?? null,
    requestId: request.requestId ?? null,
  };
}

export async function analyzeAiEvidence(request: AiEvidenceRequest): Promise<AiEvidenceResponse> {
  const response = await unwrapCommand(
    commands.analyzeAiEvidence(toAiEvidenceRequestPayload(request)),
    'analyze_ai_evidence',
  );
  return mapAiEvidenceResponsePayload(response);
}
