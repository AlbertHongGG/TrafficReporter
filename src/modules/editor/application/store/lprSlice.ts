import type { StateCreator } from 'zustand';
import type {
  EditorWorkspaceState,
  LprAnalysisProvenance,
  LprDecisionTrace,
  LprFrameSample,
  LprJobState,
  LprPlateCandidate,
  LprResultHistoryEntry,
  LprReviewState,
  LprRuntimeStatus,
  LprSessionState,
  LprTargetAnchor,
  LprTargetTrack,
  LprVehicleKind,
  LprWorkflowMode,
  TimelineIntervalSelection,
} from '../../domain/model';
import { getActiveFile } from '../../domain/model';
import {
  getLprSessionByFileId,
  setAnalysisRuntimeStatus,
  setLprSessionByFileId,
} from '../../domain/analysisState';
import { buildDefaultLprState, buildLprTargetAnchor } from '../../domain/lprState';
import type { EditorStore } from './store';

/**
 * Intentionally field-free: LPR sessions live per-file inside `workspace`
 * (`analysis.lprSessionsByFileId`), which is owned by the session slice.
 * This slice contributes the LPR action surface only. The named type is kept
 * so every slice follows one uniform `State & Actions` shape.
 */
export interface LprState {
  // No owned fields.
}

export interface LprActions {
  setLprRuntimeStatus: (runtimeStatus: LprRuntimeStatus | null) => void;
  replaceLprSession: (fileId: string, session: LprSessionState) => void;
  setLprMode: (workflowMode: LprWorkflowMode) => void;
  setLprInterval: (interval: TimelineIntervalSelection) => void;
  clearLprInterval: () => void;
  setLprAnalysisProfile: (analysisProfileId: string) => void;
  setLprTargetVehicleKind: (targetVehicleKind: LprVehicleKind) => void;
  setLprCountryHints: (countryHints: string[]) => void;
  setLprToggles: (toggles: Partial<Pick<LprSessionState, 'useDenseSampling' | 'showDeveloperDiagnostics'>>) => void;
  setLprTargetTracks: (targetTracks: LprTargetTrack[]) => void;
  setLprAnalysisTrack: (analysisTrack: LprTargetTrack | null) => void;
  selectLprTargetTrack: (targetTrackId: string | null, anchor: LprTargetAnchor | null) => void;
  setLprJob: (job: Partial<LprJobState>) => void;
  setLprSamples: (samples: LprFrameSample[]) => void;
  setLprCandidates: (candidates: LprPlateCandidate[]) => void;
  setLprReview: (review: LprReviewState | null) => void;
  setLprProvenance: (provenance: LprAnalysisProvenance | null) => void;
  setLprDecision: (decision: LprDecisionTrace | null) => void;
  acceptLprCandidate: (candidateId: string | null) => void;
  appendLprHistory: (entry: LprResultHistoryEntry) => void;
  clearLprResults: () => void;
  resetLprSession: () => void;
}

export type LprSlice = LprState & LprActions;

type LprSliceCreator = StateCreator<EditorStore, [], [], LprSlice>;

function reconcileReviewSelection(
  lprState: LprSessionState,
  candidateId: string | null,
): LprReviewState | null {
  if (!lprState.review) {
    return null;
  }

  if (!candidateId) {
    return {
      ...lprState.review,
      acceptedCandidateId: null,
      status: lprState.review.suggestedCandidateId ? 'review-required' : lprState.review.status,
    };
  }

  return {
    ...lprState.review,
    acceptedCandidateId: candidateId,
    status: 'accepted',
  };
}

/**
 * Apply a session transition to the active file's LPR session. Returns the
 * same workspace reference when there is no active file (no-op, so the
 * session revision does not bump).
 */
function updateActiveLprSession(
  workspace: EditorWorkspaceState,
  updater: (lprState: LprSessionState) => LprSessionState,
): EditorWorkspaceState {
  const activeFile = getActiveFile(workspace);
  if (!activeFile) {
    return workspace;
  }

  return {
    ...workspace,
    analysis: setLprSessionByFileId(
      workspace.analysis,
      activeFile.id,
      updater(getLprSessionByFileId(workspace.analysis, activeFile.id)),
    ),
  };
}

/** Pure action creators below: each maps a workspace to the next workspace. */

export function applySetLprRuntimeStatus(
  workspace: EditorWorkspaceState,
  runtimeStatus: LprRuntimeStatus | null,
): EditorWorkspaceState {
  return {
    ...workspace,
    analysis: setAnalysisRuntimeStatus(workspace.analysis, runtimeStatus),
  };
}

export function applyReplaceLprSession(
  workspace: EditorWorkspaceState,
  fileId: string,
  session: LprSessionState,
): EditorWorkspaceState {
  return {
    ...workspace,
    analysis: setLprSessionByFileId(workspace.analysis, fileId, session),
  };
}

export function applySetLprMode(
  workspace: EditorWorkspaceState,
  workflowMode: LprWorkflowMode,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    workflowMode,
  }));
}

export function applySetLprInterval(
  workspace: EditorWorkspaceState,
  interval: TimelineIntervalSelection,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    interval: {
      startMs: Math.max(0, Math.min(interval.startMs, interval.endMs)),
      endMs: Math.max(0, Math.max(interval.startMs, interval.endMs)),
    },
    workflowMode: lprState.workflowMode === 'idle' ? 'range' : lprState.workflowMode,
  }));
}

export function applyClearLprInterval(workspace: EditorWorkspaceState): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    interval: null,
  }));
}

export function applySetLprAnalysisProfile(
  workspace: EditorWorkspaceState,
  analysisProfileId: string,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    selectedAnalysisProfileId: analysisProfileId,
  }));
}

export function applySetLprTargetVehicleKind(
  workspace: EditorWorkspaceState,
  targetVehicleKind: LprVehicleKind,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    targetVehicleKind,
  }));
}

export function applySetLprCountryHints(
  workspace: EditorWorkspaceState,
  countryHints: string[],
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    countryHints: [...countryHints],
  }));
}

export function applySetLprToggles(
  workspace: EditorWorkspaceState,
  toggles: Partial<Pick<LprSessionState, 'useDenseSampling' | 'showDeveloperDiagnostics'>>,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    ...toggles,
  }));
}

export function applySetLprTargetTracks(
  workspace: EditorWorkspaceState,
  targetTracks: LprTargetTrack[],
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => {
    const nextTracks = buildDefaultLprState({ targetTracks }).targetTracks;
    const selectedTargetTrackId = nextTracks.some((track) => track.id === lprState.selectedTargetTrackId)
      ? lprState.selectedTargetTrackId
      : nextTracks[0]?.id ?? null;
    const selectedTargetTrack = nextTracks.find((track) => track.id === selectedTargetTrackId) ?? null;
    return {
      ...lprState,
      targetTracks: nextTracks,
      selectedTargetTrackId,
      selectedTargetAnchor: buildLprTargetAnchor(
        selectedTargetTrack,
        lprState.selectedTargetAnchor?.trackId === selectedTargetTrackId
          ? lprState.selectedTargetAnchor.timeMs
          : null,
      ),
    };
  });
}

export function applySetLprAnalysisTrack(
  workspace: EditorWorkspaceState,
  analysisTrack: LprTargetTrack | null,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    analysisTrack: buildDefaultLprState({ analysisTrack }).analysisTrack,
  }));
}

export function applySelectLprTargetTrack(
  workspace: EditorWorkspaceState,
  targetTrackId: string | null,
  anchor: LprTargetAnchor | null,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    selectedTargetTrackId: targetTrackId,
    selectedTargetAnchor: buildDefaultLprState({ selectedTargetAnchor: anchor }).selectedTargetAnchor,
    workflowMode: targetTrackId ? 'target' : lprState.workflowMode,
  }));
}

export function applySetLprJob(
  workspace: EditorWorkspaceState,
  job: Partial<LprJobState>,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    job: {
      ...lprState.job,
      ...job,
    },
  }));
}

export function applySetLprSamples(
  workspace: EditorWorkspaceState,
  samples: LprFrameSample[],
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    samples: buildDefaultLprState({ samples }).samples,
  }));
}

export function applySetLprCandidates(
  workspace: EditorWorkspaceState,
  candidates: LprPlateCandidate[],
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    candidates: buildDefaultLprState({ candidates }).candidates,
    acceptedCandidateId: candidates.some((candidate) => candidate.id === lprState.acceptedCandidateId)
      ? lprState.acceptedCandidateId
      : candidates[0]?.id ?? null,
  }));
}

export function applySetLprReview(
  workspace: EditorWorkspaceState,
  review: LprReviewState | null,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    review: review ? buildDefaultLprState({ review }).review : null,
    acceptedCandidateId: review?.acceptedCandidateId ?? null,
  }));
}

export function applySetLprProvenance(
  workspace: EditorWorkspaceState,
  provenance: LprAnalysisProvenance | null,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    lastAnalysisProvenance: provenance
      ? buildDefaultLprState({ lastAnalysisProvenance: provenance }).lastAnalysisProvenance
      : null,
  }));
}

export function applySetLprDecision(
  workspace: EditorWorkspaceState,
  decision: LprDecisionTrace | null,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    decision: decision ? buildDefaultLprState({ decision }).decision : null,
  }));
}

export function applyAcceptLprCandidate(
  workspace: EditorWorkspaceState,
  candidateId: string | null,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    review: reconcileReviewSelection(lprState, candidateId),
    acceptedCandidateId: candidateId,
    workflowMode: candidateId ? 'review' : lprState.workflowMode,
  }));
}

export function applyAppendLprHistory(
  workspace: EditorWorkspaceState,
  entry: LprResultHistoryEntry,
): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    history: [...lprState.history, buildDefaultLprState({ history: [entry] }).history[0]],
  }));
}

export function applyClearLprResults(workspace: EditorWorkspaceState): EditorWorkspaceState {
  return updateActiveLprSession(workspace, (lprState) => ({
    ...lprState,
    job: buildDefaultLprState().job,
    targetTracks: [],
    selectedTargetTrackId: null,
    selectedTargetAnchor: null,
    analysisTrack: null,
    samples: [],
    candidates: [],
    review: null,
    lastAnalysisProvenance: null,
    decision: null,
    acceptedCandidateId: null,
  }));
}

export function applyResetLprSession(workspace: EditorWorkspaceState): EditorWorkspaceState {
  return updateActiveLprSession(workspace, () => buildDefaultLprState());
}

export const createLprSlice: LprSliceCreator = (_set, get) => {
  const commit = (nextWorkspace: EditorWorkspaceState): void => {
    get().commitWorkspace(nextWorkspace);
  };

  return {
    setLprRuntimeStatus: (runtimeStatus) => {
      commit(applySetLprRuntimeStatus(get().workspace, runtimeStatus));
    },
    replaceLprSession: (fileId, session) => {
      commit(applyReplaceLprSession(get().workspace, fileId, session));
    },
    setLprMode: (workflowMode) => {
      commit(applySetLprMode(get().workspace, workflowMode));
    },
    setLprInterval: (interval) => {
      commit(applySetLprInterval(get().workspace, interval));
    },
    clearLprInterval: () => {
      commit(applyClearLprInterval(get().workspace));
    },
    setLprAnalysisProfile: (analysisProfileId) => {
      commit(applySetLprAnalysisProfile(get().workspace, analysisProfileId));
    },
    setLprTargetVehicleKind: (targetVehicleKind) => {
      commit(applySetLprTargetVehicleKind(get().workspace, targetVehicleKind));
    },
    setLprCountryHints: (countryHints) => {
      commit(applySetLprCountryHints(get().workspace, countryHints));
    },
    setLprToggles: (toggles) => {
      commit(applySetLprToggles(get().workspace, toggles));
    },
    setLprTargetTracks: (targetTracks) => {
      commit(applySetLprTargetTracks(get().workspace, targetTracks));
    },
    setLprAnalysisTrack: (analysisTrack) => {
      commit(applySetLprAnalysisTrack(get().workspace, analysisTrack));
    },
    selectLprTargetTrack: (targetTrackId, anchor) => {
      commit(applySelectLprTargetTrack(get().workspace, targetTrackId, anchor));
    },
    setLprJob: (job) => {
      commit(applySetLprJob(get().workspace, job));
    },
    setLprSamples: (samples) => {
      commit(applySetLprSamples(get().workspace, samples));
    },
    setLprCandidates: (candidates) => {
      commit(applySetLprCandidates(get().workspace, candidates));
    },
    setLprReview: (review) => {
      commit(applySetLprReview(get().workspace, review));
    },
    setLprProvenance: (provenance) => {
      commit(applySetLprProvenance(get().workspace, provenance));
    },
    setLprDecision: (decision) => {
      commit(applySetLprDecision(get().workspace, decision));
    },
    acceptLprCandidate: (candidateId) => {
      commit(applyAcceptLprCandidate(get().workspace, candidateId));
    },
    appendLprHistory: (entry) => {
      commit(applyAppendLprHistory(get().workspace, entry));
    },
    clearLprResults: () => {
      commit(applyClearLprResults(get().workspace));
    },
    resetLprSession: () => {
      commit(applyResetLprSession(get().workspace));
    },
  };
};
