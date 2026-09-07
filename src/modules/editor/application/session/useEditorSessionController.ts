import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import {
  commands,
  type EditorFileState as RustEditorFileState,
  type EditorWorkspaceState as RustEditorWorkspaceState,
  type RenderProfilePayload,
} from '../../../../types/bindings';
import type {
  AudioBitrateKbps,
  EditorFilePayload,
  EditorWorkspacePayload,
  VideoQuality,
} from '../../domain/model';
import type { ExportFormat } from '../../../export/domain/model';
import type { EditorAction } from '../editorReducer';
import { createEditorSessionStoreState, reduceEditorSessionStoreState } from './sessionStore';

/**
 * IPC snapshot → frontend workspace mapper (Blueprint §1.2, Phase 1-D).
 *
 * The backend snapshot is a transport view: nullable-over-the-wire scalars,
 * and — per the contract — its `analysis` carries only `lprRuntimeStatus`.
 * Session maps (`lprSessionsByFileId` / `aiEvidenceSessionsByFileId`) are
 * frontend-owned (see `domain/analysisState.ts`) and are never read off the
 * wire, so no `Value`/`any` session state crosses IPC in either direction.
 * No assertions; wire-nulls resolve to domain defaults.
 */
function toExportFormat(format: string): ExportFormat {
  return format === 'mkv' ? 'mkv' : 'mp4';
}

function toVideoQuality(value: string | null | undefined): VideoQuality | undefined {
  switch (value) {
    case 'source':
    case '2160p':
    case '1440p':
    case '1080p':
    case '720p':
    case '480p':
      return value;
    default:
      return undefined;
  }
}

function toAudioBitrateKbps(value: number | null | undefined): AudioBitrateKbps | undefined {
  switch (value) {
    case 320:
    case 256:
    case 192:
    case 128:
    case 96:
      return value;
    default:
      return undefined;
  }
}

function toEditorFilePayload(remoteFile: RustEditorFileState): EditorFilePayload {
  return {
    id: remoteFile.id,
    asset: remoteFile.asset,
    track: remoteFile.track,
    clips: remoteFile.clips.map((clip) => ({
      id: clip.id,
      assetId: clip.assetId,
      trackId: clip.trackId,
      startMs: clip.startMs ?? 0,
      inPointMs: clip.inPointMs ?? 0,
      outPointMs: clip.outPointMs ?? 0,
      muted: clip.muted,
    })),
    renderProfile: {
      format: toExportFormat(remoteFile.renderProfile.format),
      fps: remoteFile.renderProfile.fps,
      videoQuality: toVideoQuality(remoteFile.renderProfile.videoQuality),
      audioBitrateKbps: toAudioBitrateKbps(remoteFile.renderProfile.audioBitrateKbps),
      compressionMode: remoteFile.renderProfile.compressionMode,
    },
  };
}

function toEditorWorkspacePayload(remote: RustEditorWorkspaceState): EditorWorkspacePayload {
  return {
    workspaceName: remote.workspaceName,
    activeFileId: remote.activeFileId,
    files: remote.files.map(toEditorFilePayload),
    analysis: {
      lprRuntimeStatus: remote.analysis.lprRuntimeStatus,
      lprSessionsByFileId: {},
      aiEvidenceSessionsByFileId: {},
    },
  };
}

export function useEditorSessionController() {
  const [session, setSession] = useState(() => createEditorSessionStoreState());
  const latestSessionRef = useRef(session);
  useLayoutEffect(() => {
    latestSessionRef.current = session;
  });

  useEffect(() => {
    // 1. Fetch initial state from Rust
    commands.getAppState()
      .then((res) => {
        if (res.status === 'ok') {
          setSession((currentSession) => reduceEditorSessionStoreState(currentSession, {
            type: 'sync-workspace-state',
            workspace: toEditorWorkspacePayload(res.data),
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
        workspace: toEditorWorkspacePayload(event.payload),
      }));
    });

    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  const dispatch = useCallback((action: EditorAction) => {
    // Apply optimistic update immediately to local session store
    setSession((currentSession) => reduceEditorSessionStoreState(currentSession, action));

    const currentWorkspace = latestSessionRef.current.workspace;

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
        const fileId = currentWorkspace.activeFileId;
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
        const fileId = currentWorkspace.activeFileId;
        if (fileId) {
          const clip = currentWorkspace.files.find((f) => f.id === fileId)?.clips.find((c) => c.id === action.clipId);
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
        const fileId = currentWorkspace.activeFileId;
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
        const fileId = currentWorkspace.activeFileId;
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
        const file = currentWorkspace.files.find((f) => f.id === currentWorkspace.activeFileId);
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
        const file = currentWorkspace.files.find((f) => f.id === currentWorkspace.activeFileId);
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
        const file = currentWorkspace.files.find((f) => f.id === currentWorkspace.activeFileId);
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
  }, []);

  return {
    state: session.workspace,
    dispatch,
    sessionRevision: session.revision,
    sessionUpdatedAt: session.updatedAt,
  };
}
