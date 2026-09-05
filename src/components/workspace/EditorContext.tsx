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

export const EditorProvider: React.FC<{
  children: React.ReactNode;
  value?: EditorContextValue;
}> = ({ children, value: externalValue }) => {
  const internal = useEditorSessionController();

  const internalActiveFile = useMemo(() => {
    return internal.state?.files?.find(f => f.id === internal.state?.activeFileId);
  }, [internal.state?.files, internal.state?.activeFileId]);

  const contextValue = useMemo(() => {
    if (externalValue) {
      return externalValue;
    }
    return {
      state: internal.state,
      dispatch: internal.dispatch,
      activeFile: internalActiveFile,
    };
  }, [externalValue, internal.state, internal.dispatch, internalActiveFile]);

  return (
    <EditorContext.Provider value={contextValue}>
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
