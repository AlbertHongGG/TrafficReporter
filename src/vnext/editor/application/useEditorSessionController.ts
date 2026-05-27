import { useCallback, useState } from 'react';
import type { EditorAction } from '../../../modules/editor/application/editorReducer';
import { createEditorSessionStoreState, reduceEditorSessionStoreState } from './sessionStore';

export function useEditorSessionController() {
  const [session, setSession] = useState(() => createEditorSessionStoreState());

  const dispatch = useCallback((action: EditorAction) => {
    setSession((currentSession) => reduceEditorSessionStoreState(currentSession, action));
  }, []);

  return {
    state: session.workspace,
    dispatch,
    sessionRevision: session.revision,
    sessionUpdatedAt: session.updatedAt,
  };
}