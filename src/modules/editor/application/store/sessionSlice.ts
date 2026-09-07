import type { StateCreator } from 'zustand';
import { buildDefaultWorkspaceState } from '../../domain/model';
import type { EditorWorkspaceState } from '../../domain/model';
import type { EditorStore } from './store';

export interface SessionState {
  workspace: EditorWorkspaceState;
  revision: number;
  updatedAt: string;
}

export interface SessionActions {
  /**
   * Commit a next workspace. Reference equality means "no change": the call
   * is a no-op and the revision does NOT increase.
   */
  commitWorkspace: (nextWorkspace: EditorWorkspaceState, updatedAt?: string) => void;
  /** Reset to a fresh default workspace with revision back at 0. */
  resetSession: (updatedAt?: string) => void;
}

export type SessionSlice = SessionState & SessionActions;

type SessionSliceCreator = StateCreator<EditorStore, [], [], SessionSlice>;

export function createInitialSessionState(
  workspace: EditorWorkspaceState = buildDefaultWorkspaceState(),
  updatedAt: string = new Date().toISOString(),
): SessionState {
  return {
    workspace,
    revision: 0,
    updatedAt,
  };
}

/**
 * Pure session transition. When `nextWorkspace` is the very same reference as
 * the current one, the input state object is returned unchanged and the
 * revision does NOT increase. This preserves the revision semantics of the
 * previous 36-line session container that this slice replaces.
 */
export function commitWorkspaceState(
  state: SessionState,
  nextWorkspace: EditorWorkspaceState,
  updatedAt: string = new Date().toISOString(),
): SessionState {
  if (nextWorkspace === state.workspace) {
    return state;
  }

  return {
    workspace: nextWorkspace,
    revision: state.revision + 1,
    updatedAt,
  };
}

export const createSessionSlice: SessionSliceCreator = (set, get) => ({
  ...createInitialSessionState(),
  commitWorkspace: (nextWorkspace, updatedAt = new Date().toISOString()) => {
    const current = get();
    if (nextWorkspace === current.workspace) {
      return;
    }
    set({
      workspace: nextWorkspace,
      revision: current.revision + 1,
      updatedAt,
    });
  },
  resetSession: (updatedAt = new Date().toISOString()) => {
    set({
      workspace: buildDefaultWorkspaceState(),
      revision: 0,
      updatedAt,
    });
  },
});
