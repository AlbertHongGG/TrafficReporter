import type { StateCreator } from 'zustand';
import type { EditorWorkspaceState, OperationFeedback } from '../../domain/model';
import type { EditorStore } from './store';

export interface UiState {
  lastFeedback: OperationFeedback | null;
}

export interface UiActions {
  pushFeedback: (feedback: OperationFeedback) => void;
  clearFeedback: () => void;
  setWorkspaceName: (workspaceName: string) => void;
}

export type UiSlice = UiState & UiActions;

type UiSliceCreator = StateCreator<EditorStore, [], [], UiSlice>;

/**
 * Pure workspace-name transition. Returns the same reference when the name
 * is unchanged so the session revision does not bump on no-ops.
 */
export function applyWorkspaceName(
  workspace: EditorWorkspaceState,
  workspaceName: string,
): EditorWorkspaceState {
  if (workspace.workspaceName === workspaceName) {
    return workspace;
  }

  return {
    ...workspace,
    workspaceName,
  };
}

export const createUiSlice: UiSliceCreator = (set, get) => ({
  lastFeedback: null,
  pushFeedback: (feedback) => {
    set({
      lastFeedback: { ...feedback },
    });
  },
  clearFeedback: () => {
    set({ lastFeedback: null });
  },
  setWorkspaceName: (workspaceName) => {
    get().commitWorkspace(applyWorkspaceName(get().workspace, workspaceName));
  },
});
