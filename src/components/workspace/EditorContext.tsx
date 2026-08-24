import React, { createContext, useContext, useMemo } from 'react';
import { useEditorSessionController } from '../../vnext/editor/application/useEditorSessionController';
import type { EditorWorkspaceState, EditorFileState } from '../../modules/editor/domain/model';
import type { EditorAction } from '../../modules/editor/application/editorReducer';

interface EditorContextValue {
  state: EditorWorkspaceState;
  dispatch: React.Dispatch<EditorAction>;
  activeFile: EditorFileState | undefined;
}

const EditorContext = createContext<EditorContextValue | null>(null);

export const EditorProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { state, dispatch } = useEditorSessionController();

  const activeFile = useMemo(() => {
    return state.files.find(f => f.id === state.activeFileId);
  }, [state.files, state.activeFileId]);

  const value = useMemo(() => ({
    state,
    dispatch,
    activeFile,
  }), [state, dispatch, activeFile]);

  return (
    <EditorContext.Provider value={value}>
      {children}
    </EditorContext.Provider>
  );
};

export function useEditorContext() {
  const context = useContext(EditorContext);
  if (!context) {
    throw new Error('useEditorContext must be used within EditorProvider');
  }
  return context;
}
