import { editorReducer, createInitialEditorState, type EditorAction } from '../editorReducer';
import type { EditorWorkspaceState } from '../../domain/model';

export interface EditorSessionStoreState {
  revision: number;
  updatedAt: string;
  workspace: EditorWorkspaceState;
}

export function createEditorSessionStoreState(
  workspace: EditorWorkspaceState = createInitialEditorState(),
  updatedAt = new Date().toISOString(),
): EditorSessionStoreState {
  return {
    revision: 0,
    updatedAt,
    workspace,
  };
}

export function reduceEditorSessionStoreState(
  state: EditorSessionStoreState,
  action: EditorAction,
  updatedAt = new Date().toISOString(),
): EditorSessionStoreState {
  const nextWorkspace = editorReducer(state.workspace, action);
  if (nextWorkspace === state.workspace) {
    return state;
  }

  return {
    revision: state.revision + 1,
    updatedAt,
    workspace: nextWorkspace,
  };
}
