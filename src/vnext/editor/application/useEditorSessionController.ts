import { useCallback, useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import type { EditorWorkspacePayload } from '../../../modules/editor/domain/model';
import type { EditorAction } from '../../../modules/editor/application/editorReducer';
import { createEditorSessionStoreState, reduceEditorSessionStoreState } from './sessionStore';

export function useEditorSessionController() {
  const [session, setSession] = useState(() => createEditorSessionStoreState());

  useEffect(() => {
    // 1. Fetch initial state from Rust
    invoke<EditorWorkspacePayload>('get_app_state')
      .then((initialState) => {
        setSession((currentSession) => reduceEditorSessionStoreState(currentSession, {
           type: 'sync-workspace-state',
           workspace: initialState
        }));
      })
      .catch((error) => {
        console.error('Failed to get initial app state from Rust:', error);
      });

    // 2. Listen to state updates from Rust
    const unlisten = listen<EditorWorkspacePayload>('editor/state-updated', (event) => {
      setSession((currentSession) => reduceEditorSessionStoreState(currentSession, {
        type: 'sync-workspace-state',
        workspace: event.payload,
      }));
    });

    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  const dispatch = useCallback((action: EditorAction) => {
    // Intercept core domain mutations and send to Rust
    switch (action.type) {
      case 'add-files':
        invoke('workspace_add_files', { assets: action.assets });
        return;
      case 'remove-file':
        invoke('workspace_remove_file', { fileId: action.fileId });
        return;
      case 'set-active-file':
        invoke('workspace_set_active_file', { fileId: action.fileId });
        return;
      case 'move-clip': {
        const fileId = session.workspace.activeFileId;
        if (fileId) invoke('workspace_move_clip', { fileId, clipId: action.clipId, startMs: action.startMs });
        return;
      }
      case 'trim-clip-start': {
        const fileId = session.workspace.activeFileId;
        // The reducer uses startMs internally too, we need to pass startMs.
        // Wait, the action only has inPointMs! We'll just let Rust compute startMs or we pass the current startMs.
        // Actually, the Reducer does: clip.startMs + (inPointMs - clip.inPointMs).
        // Let's pass the computed startMs to Rust.
        if (fileId) {
            const clip = session.workspace.files.find(f => f.id === fileId)?.clips.find(c => c.id === action.clipId);
            if (clip) {
               const newStartMs = clip.startMs + (action.inPointMs - clip.inPointMs);
               invoke('workspace_trim_clip_start', { fileId, clipId: action.clipId, inPointMs: action.inPointMs, startMs: newStartMs });
            }
        }
        return;
      }
      case 'trim-clip-end': {
        const fileId = session.workspace.activeFileId;
        if (fileId) invoke('workspace_trim_clip_end', { fileId, clipId: action.clipId, outPointMs: action.outPointMs });
        return;
      }
      case 'split-clip': {
        const fileId = session.workspace.activeFileId;
        if (fileId) invoke('workspace_split_clip', { fileId, clipId: action.clipId, atMs: action.atMs });
        return;
      }
      case 'delete-selected-clips': {
        const file = session.workspace.files.find(f => f.id === session.workspace.activeFileId);
        if (file) invoke('workspace_delete_clips', { fileId: file.id, clipIds: file.selectedClipIds });
        return;
      }
      case 'set-selected-clips-muted': {
        const file = session.workspace.files.find(f => f.id === session.workspace.activeFileId);
        if (file) invoke('workspace_set_clips_muted', { fileId: file.id, clipIds: file.selectedClipIds, muted: action.muted });
        return;
      }
      case 'set-render-profile': {
        const file = session.workspace.files.find(f => f.id === session.workspace.activeFileId);
        if (file) {
            const newProfile = { ...file.renderProfile, ...action.renderProfile };
            invoke('workspace_set_render_profile', { fileId: file.id, renderProfile: newProfile });
        }
        return;
      }
    }

    // Process UI and LPR state locally
    setSession((currentSession) => reduceEditorSessionStoreState(currentSession, action));
  }, [session.workspace]);

  return {
    state: session.workspace,
    dispatch,
    sessionRevision: session.revision,
    sessionUpdatedAt: session.updatedAt,
  };
}