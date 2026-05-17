import type { LprRuntimeStatus, LprSessionState } from '../../../shared/contracts';
import { buildDefaultLprState } from './lprState';

export interface EditorAnalysisState {
  lprRuntimeStatus: LprRuntimeStatus | null;
  lprSessionsByFileId: Record<string, LprSessionState>;
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

export function buildDefaultAnalysisState(overrides: Partial<EditorAnalysisState> = {}): EditorAnalysisState {
  return {
    lprRuntimeStatus: cloneRuntimeStatus(overrides.lprRuntimeStatus ?? null),
    lprSessionsByFileId: cloneLprSessionsByFileId(overrides.lprSessionsByFileId ?? {}),
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
  const nextEntries = Object.entries(analysisState.lprSessionsByFileId)
    .filter(([fileId]) => validFileIdSet.has(fileId));

  if (nextEntries.length === Object.keys(analysisState.lprSessionsByFileId).length) {
    return analysisState;
  }

  return {
    ...analysisState,
    lprSessionsByFileId: Object.fromEntries(nextEntries),
  };
}