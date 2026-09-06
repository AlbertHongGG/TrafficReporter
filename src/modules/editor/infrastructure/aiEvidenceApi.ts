import { commands } from '../../../types/bindings';
import type { AiEvidenceRequest, AiEvidenceResponse } from '../domain/aiEvidenceState';

export async function analyzeAiEvidence(request: AiEvidenceRequest): Promise<AiEvidenceResponse> {
  const res = await commands.analyzeAiEvidence(request as any);
  if (res.status === 'ok') {
    return res.data as unknown as AiEvidenceResponse;
  }
  throw new Error(res.error);
}