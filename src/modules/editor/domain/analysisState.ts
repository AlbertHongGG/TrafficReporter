import type { AiEvidenceSessionState, LprRuntimeStatus, LprSessionState } from '../../../shared/contracts';
import { buildDefaultAiEvidenceState } from './aiEvidenceState';
import { buildDefaultLprState } from './lprState';

export interface EditorAnalysisState {
  lprRuntimeStatus: LprRuntimeStatus | null;
  lprSessionsByFileId: Record<string, LprSessionState>;
  aiEvidenceSessionsByFileId: Record<string, AiEvidenceSessionState>;
}

function cloneRuntimeStatus(runtimeStatus: LprRuntimeStatus | null) {
  return runtimeStatus ? {
    ...runtimeStatus,
    missingPackages: [...runtimeStatus.missingPackages],
    installedPackages: [...runtimeStatus.installedPackages],
  } : null;
}

function cloneLprSessionsByFileId(lprSessionsByFileId: Record<string, LprSessionState>) {
  return Object.fromEntries(
    Object.entries(lprSessionsByFileId).map(([fileId, session]) => [fileId, buildDefaultLprState(session)]),
  );
}

function cloneAiEvidenceSessionsByFileId(aiEvidenceSessionsByFileId: Record<string, AiEvidenceSessionState>) {
  return Object.fromEntries(
    Object.entries(aiEvidenceSessionsByFileId).map(([fileId, session]) => [fileId, buildDefaultAiEvidenceState(session)]),
  );
}

export function buildDefaultAnalysisState(overrides: Partial<EditorAnalysisState> = {}): EditorAnalysisState {
  return {
    lprRuntimeStatus: cloneRuntimeStatus(overrides.lprRuntimeStatus ?? null),
    lprSessionsByFileId: cloneLprSessionsByFileId(overrides.lprSessionsByFileId ?? {}),
    aiEvidenceSessionsByFileId: cloneAiEvidenceSessionsByFileId(overrides.aiEvidenceSessionsByFileId ?? {}),
  };
}

export function getLprSessionByFileId(analysisState: EditorAnalysisState, fileId: string | null | undefined): LprSessionState {
  if (!fileId) {
    return buildDefaultLprState();
  }

  return analysisState.lprSessionsByFileId[fileId] ?? buildDefaultLprState();
}

export function setLprSessionByFileId(
  analysisState: EditorAnalysisState,
  fileId: string,
  session: LprSessionState,
): EditorAnalysisState {
  return {
    ...analysisState,
    lprSessionsByFileId: {
      ...analysisState.lprSessionsByFileId,
      [fileId]: buildDefaultLprState(session),
    },
  };
}

export function getAiEvidenceSessionByFileId(
  analysisState: EditorAnalysisState,
  fileId: string | null | undefined,
): AiEvidenceSessionState {
  if (!fileId) {
    return buildDefaultAiEvidenceState();
  }

  return analysisState.aiEvidenceSessionsByFileId[fileId] ?? buildDefaultAiEvidenceState();
}

export function setAiEvidenceSessionByFileId(
  analysisState: EditorAnalysisState,
  fileId: string,
  session: AiEvidenceSessionState,
): EditorAnalysisState {
  return {
    ...analysisState,
    aiEvidenceSessionsByFileId: {
      ...analysisState.aiEvidenceSessionsByFileId,
      [fileId]: buildDefaultAiEvidenceState(session),
    },
  };
}

export function setAnalysisRuntimeStatus(
  analysisState: EditorAnalysisState,
  runtimeStatus: LprRuntimeStatus | null,
): EditorAnalysisState {
  return {
    ...analysisState,
    lprRuntimeStatus: cloneRuntimeStatus(runtimeStatus),
  };
}

export function pruneAnalysisSessions(analysisState: EditorAnalysisState, validFileIds: string[]): EditorAnalysisState {
  const validFileIdSet = new Set(validFileIds);
  const nextLprEntries = Object.entries(analysisState.lprSessionsByFileId)
    .filter(([fileId]) => validFileIdSet.has(fileId));
  const nextAiEvidenceEntries = Object.entries(analysisState.aiEvidenceSessionsByFileId)
    .filter(([fileId]) => validFileIdSet.has(fileId));

  if (
    nextLprEntries.length === Object.keys(analysisState.lprSessionsByFileId).length
    && nextAiEvidenceEntries.length === Object.keys(analysisState.aiEvidenceSessionsByFileId).length
  ) {
    return analysisState;
  }

  return {
    ...analysisState,
    lprSessionsByFileId: Object.fromEntries(nextLprEntries),
    aiEvidenceSessionsByFileId: Object.fromEntries(nextAiEvidenceEntries),
  };
}