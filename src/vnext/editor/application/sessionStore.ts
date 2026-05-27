import { editorReducer, initialEditorState, type EditorAction } from '../../../modules/editor/application/editorReducer';
import type { EditorWorkspaceState } from '../../../modules/editor/domain/model';

export interface EditorSessionStoreState {
  revision: number;
  updatedAt: string;
  workspace: EditorWorkspaceState;
}

export function createEditorSessionStoreState(
  workspace: EditorWorkspaceState = initialEditorState,
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