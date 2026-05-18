import { invoke } from '@tauri-apps/api/core';
import type { AiEvidenceResponse, AiEvidenceRequest } from '../../../shared/contracts';

export function analyzeAiEvidence(request: AiEvidenceRequest) {
  return invoke<AiEvidenceResponse>('analyze_ai_evidence', { request });
}