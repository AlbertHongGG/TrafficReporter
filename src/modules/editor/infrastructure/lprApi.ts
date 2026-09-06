import { commands } from '../../../types/bindings';
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

async function unwrap<T>(promise: Promise<{ status: 'ok'; data: T } | { status: 'error'; error: string }>): Promise<T> {
  const res = await promise;
  if (res.status === 'ok') {
    return res.data;
  }
  throw new Error(res.error);
}

export function getLprRuntimeStatus(): Promise<LprRuntimeStatus> {
  return unwrap(commands.getLprRuntimeStatus()) as unknown as Promise<LprRuntimeStatus>;
}

export function cancelLprRuntimeJob(): Promise<boolean> {
  return unwrap(commands.cancelLprRuntimeJob());
}

export function scanLprTargets(request: LprTargetScanRequest): Promise<LprTargetScanResponse> {
  return unwrap(commands.scanLprTargets(request as any)) as unknown as Promise<LprTargetScanResponse>;
}

export function analyzeLprFrame(request: LprFrameAnalysisRequest): Promise<LprFrameAnalysisResponse> {
  return unwrap(commands.analyzeLprFrame(request as any)) as unknown as Promise<LprFrameAnalysisResponse>;
}

export function analyzeLprInterval(request: LprIntervalAnalysisRequest): Promise<LprIntervalAnalysisResponse> {
  return unwrap(commands.analyzeLprInterval(request as any)) as unknown as Promise<LprIntervalAnalysisResponse>;
}

export function exportLprEvidence(request: LprEvidenceExportRequest): Promise<LprEvidenceExportResponse> {
  return unwrap(commands.exportLprEvidence(request as any)) as unknown as Promise<LprEvidenceExportResponse>;
}