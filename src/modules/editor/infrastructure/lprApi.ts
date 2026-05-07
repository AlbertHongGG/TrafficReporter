import { invoke } from '@tauri-apps/api/core';
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
} from '../../../shared/contracts';

export function getLprRuntimeStatus() {
  return invoke<LprRuntimeStatus>('get_lpr_runtime_status');
}

export function scanLprTargets(request: LprTargetScanRequest) {
  return invoke<LprTargetScanResponse>('scan_lpr_targets', { request });
}

export function analyzeLprFrame(request: LprFrameAnalysisRequest) {
  return invoke<LprFrameAnalysisResponse>('analyze_lpr_frame', { request });
}

export function analyzeLprInterval(request: LprIntervalAnalysisRequest) {
  return invoke<LprIntervalAnalysisResponse>('analyze_lpr_interval', { request });
}

export function exportLprEvidence(request: LprEvidenceExportRequest) {
  return invoke<LprEvidenceExportResponse>('export_lpr_evidence', { request });
}