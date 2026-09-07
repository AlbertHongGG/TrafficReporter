import type { StateCreator } from 'zustand';
import type {
  AiEvidenceJobState,
  AiEvidenceResponse,
  AiEvidenceSessionState,
  EditorWorkspaceState,
} from '../../domain/model';
import {
  getAiEvidenceSessionByFileId,
  setAiEvidenceSessionByFileId,
} from '../../domain/analysisState';
import { buildDefaultAiEvidenceState } from '../../domain/aiEvidenceState';
import type { EditorStore } from './store';

/**
 * Intentionally field-free: AI evidence sessions live per-file inside
 * `workspace` (`analysis.aiEvidenceSessionsByFileId`), which is owned by the
 * session slice. This slice contributes the AI evidence action surface only.
 * The named type is kept so every slice follows one uniform
 * `State & Actions` shape.
 */
export interface AiState {
  // No owned fields.
}

export interface AiActions {
  setAiPrompt: (fileId: string, prompt: string) => void;
  setAiJob: (fileId: string, job: Partial<AiEvidenceJobState>) => void;
  setAiResult: (fileId: string, result: AiEvidenceResponse | null) => void;
  resetAiSession: (fileId: string) => void;
}

export type AiSlice = AiState & AiActions;

type AiSliceCreator = StateCreator<EditorStore, [], [], AiSlice>;

function updateAiEvidenceSessionByFileId(
  workspace: EditorWorkspaceState,
  fileId: string,
  updater: (aiState: AiEvidenceSessionState) => AiEvidenceSessionState,
): EditorWorkspaceState {
  return {
    ...workspace,
    analysis: setAiEvidenceSessionByFileId(
      workspace.analysis,
      fileId,
      updater(getAiEvidenceSessionByFileId(workspace.analysis, fileId)),
    ),
  };
}

/** Pure action creators below: each maps a workspace to the next workspace. */

export function applySetAiPrompt(
  workspace: EditorWorkspaceState,
  fileId: string,
  prompt: string,
): EditorWorkspaceState {
  return updateAiEvidenceSessionByFileId(workspace, fileId, (aiState) => ({
    ...aiState,
    prompt,
  }));
}

export function applySetAiJob(
  workspace: EditorWorkspaceState,
  fileId: string,
  job: Partial<AiEvidenceJobState>,
): EditorWorkspaceState {
  return updateAiEvidenceSessionByFileId(workspace, fileId, (aiState) => ({
    ...aiState,
    job: {
      ...aiState.job,
      ...job,
    },
  }));
}

export function applySetAiResult(
  workspace: EditorWorkspaceState,
  fileId: string,
  result: AiEvidenceResponse | null,
  completedAt: string = new Date().toISOString(),
): EditorWorkspaceState {
  return updateAiEvidenceSessionByFileId(workspace, fileId, (aiState) => ({
    ...aiState,
    result: result ? buildDefaultAiEvidenceState({ result }).result : null,
    lastCompletedAt: result ? completedAt : aiState.lastCompletedAt,
  }));
}

export function applyResetAiSession(
  workspace: EditorWorkspaceState,
  fileId: string,
): EditorWorkspaceState {
  return updateAiEvidenceSessionByFileId(workspace, fileId, () => buildDefaultAiEvidenceState());
}

export const createAiSlice: AiSliceCreator = (_set, get) => {
  const commit = (nextWorkspace: EditorWorkspaceState): void => {
    get().commitWorkspace(nextWorkspace);
  };

  return {
    setAiPrompt: (fileId, prompt) => {
      commit(applySetAiPrompt(get().workspace, fileId, prompt));
    },
    setAiJob: (fileId, job) => {
      commit(applySetAiJob(get().workspace, fileId, job));
    },
    setAiResult: (fileId, result) => {
      commit(applySetAiResult(get().workspace, fileId, result));
    },
    resetAiSession: (fileId) => {
      commit(applyResetAiSession(get().workspace, fileId));
    },
  };
};
