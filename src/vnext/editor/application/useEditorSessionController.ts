import { useCallback, useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import {
  commands,
  type EditorWorkspaceState as RustEditorWorkspaceState,
  type RenderProfilePayload,
} from '../../../types/bindings';
import type { EditorWorkspacePayload } from '../../../modules/editor/domain/model';
import type { EditorAction } from '../../../modules/editor/application/editorReducer';
import { createEditorSessionStoreState, reduceEditorSessionStoreState } from './sessionStore';

export function useEditorSessionController() {
  const [session, setSession] = useState(() => createEditorSessionStoreState());

  useEffect(() => {
    // 1. Fetch initial state from Rust
    commands.getAppState()
      .then((res) => {
        if (res.status === 'ok') {
          setSession((currentSession) => reduceEditorSessionStoreState(currentSession, {
            type: 'sync-workspace-state',
            workspace: res.data as unknown as EditorWorkspacePayload,
          }));
        } else {
          console.error('Failed to get initial app state from Rust:', res.error);
        }
      })
      .catch((error) => {
        console.error('Failed to get initial app state from Rust:', error);
      });

    // 2. Listen to state updates from Rust
    const unlisten = listen<RustEditorWorkspaceState>('editor/state-updated', (event) => {
      setSession((currentSession) => reduceEditorSessionStoreState(currentSession, {
        type: 'sync-workspace-state',
        workspace: event.payload as unknown as EditorWorkspacePayload,
      }));
    });

    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  const dispatch = useCallback((action: EditorAction) => {
    // Apply optimistic update immediately to local session store
    setSession((currentSession) => reduceEditorSessionStoreState(currentSession, action));

    // Synchronize core domain mutations with Rust backend
    switch (action.type) {
      case 'add-files':
        commands.workspaceAddFiles(action.assets)
          .then((res) => {
            if (res.status === 'error') {
              console.error('Failed to add files to Rust workspace:', res.error);
            }
          })
          .catch((err) => {
            console.error('Unexpected error calling workspaceAddFiles:', err);
          });
        break;

      case 'remove-file':
        commands.workspaceRemoveFile(action.fileId)
          .then((res) => {
            if (res.status === 'error') {
              console.error('Failed to remove file from Rust workspace:', res.error);
            }
          })
          .catch(console.error);
        break;

      case 'set-active-file':
        commands.workspaceSetActiveFile(action.fileId)
          .then((res) => {
            if (res.status === 'error') {
              console.error('Failed to set active file in Rust workspace:', res.error);
            }
          })
          .catch(console.error);
        break;

      case 'move-clip': {
        const fileId = session.workspace.activeFileId;
        if (fileId) {
          commands.workspaceMoveClip(fileId, action.clipId, action.startMs)
            .then((res) => {
              if (res.status === 'error') {
                console.error('Failed to move clip in Rust workspace:', res.error);
              }
            })
            .catch(console.error);
        }
        break;
      }

      case 'trim-clip-start': {
        const fileId = session.workspace.activeFileId;
        if (fileId) {
          const clip = session.workspace.files.find((f) => f.id === fileId)?.clips.find((c) => c.id === action.clipId);
          if (clip) {
            const newStartMs = clip.startMs + (action.inPointMs - clip.inPointMs);
            commands.workspaceTrimClipStart(fileId, action.clipId, action.inPointMs, newStartMs)
              .then((res) => {
                if (res.status === 'error') {
                  console.error('Failed to trim clip start in Rust workspace:', res.error);
                }
              })
              .catch(console.error);
          }
        }
        break;
      }

      case 'trim-clip-end': {
        const fileId = session.workspace.activeFileId;
        if (fileId) {
          commands.workspaceTrimClipEnd(fileId, action.clipId, action.outPointMs)
            .then((res) => {
              if (res.status === 'error') {
                console.error('Failed to trim clip end in Rust workspace:', res.error);
              }
            })
            .catch(console.error);
        }
        break;
      }

      case 'split-clip': {
        const fileId = session.workspace.activeFileId;
        if (fileId) {
          commands.workspaceSplitClip(fileId, action.clipId, action.atMs)
            .then((res) => {
              if (res.status === 'error') {
                console.error('Failed to split clip in Rust workspace:', res.error);
              }
            })
            .catch(console.error);
        }
        break;
      }

      case 'delete-selected-clips': {
        const file = session.workspace.files.find((f) => f.id === session.workspace.activeFileId);
        if (file) {
          commands.workspaceDeleteClips(file.id, file.selectedClipIds)
            .then((res) => {
              if (res.status === 'error') {
                console.error('Failed to delete clips in Rust workspace:', res.error);
              }
            })
            .catch(console.error);
        }
        break;
      }

      case 'set-selected-clips-muted': {
        const file = session.workspace.files.find((f) => f.id === session.workspace.activeFileId);
        if (file) {
          commands.workspaceSetClipsMuted(file.id, file.selectedClipIds, action.muted)
            .then((res) => {
              if (res.status === 'error') {
                console.error('Failed to mute clips in Rust workspace:', res.error);
              }
            })
            .catch(console.error);
        }
        break;
      }

      case 'set-render-profile': {
        const file = session.workspace.files.find((f) => f.id === session.workspace.activeFileId);
        if (file) {
          const newProfile: RenderProfilePayload = {
            format: action.renderProfile.format ?? file.renderProfile.format,
            fps: action.renderProfile.fps ?? file.renderProfile.fps,
            videoQuality: action.renderProfile.videoQuality ?? file.renderProfile.videoQuality ?? null,
            audioBitrateKbps: action.renderProfile.audioBitrateKbps ?? file.renderProfile.audioBitrateKbps ?? null,
            compressionMode: action.renderProfile.compressionMode ?? file.renderProfile.compressionMode ?? 'standard',
          };
          commands.workspaceSetRenderProfile(file.id, newProfile)
            .then((res) => {
              if (res.status === 'error') {
                console.error('Failed to set render profile in Rust workspace:', res.error);
              }
            })
            .catch(console.error);
        }
        break;
      }

      default:
        break;
    }
  }, [session.workspace]);

  return {
    state: session.workspace,
    dispatch,
    sessionRevision: session.revision,
    sessionUpdatedAt: session.updatedAt,
  };
}