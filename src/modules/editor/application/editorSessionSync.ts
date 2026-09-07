import { useEffect } from 'react';
import { listen } from '@tauri-apps/api/event';
import type {
  EditorFileState as RustEditorFileState,
  EditorWorkspaceState as RustEditorWorkspaceState,
} from '../../../platform/ipc/bindings';
import type {
  AudioBitrateKbps,
  EditorAsset,
  EditorFilePayload,
  EditorWorkspacePayload,
  EditorWorkspaceState,
  RenderProfile,
  VideoQuality,
} from '../domain/model';
import { DEFAULT_ZOOM } from '../domain/model';
import type { ExportFormat } from '../../export/domain/model';
import { useEditorStore } from './store/store';
import {
  fetchAppState,
  notifyWorkspaceAddFiles,
  notifyWorkspaceDeleteClips,
  notifyWorkspaceMoveClip,
  notifyWorkspaceRemoveFile,
  notifyWorkspaceSetActiveFile,
  notifyWorkspaceSetClipsMuted,
  notifyWorkspaceSetRenderProfile,
  notifyWorkspaceSplitClip,
  notifyWorkspaceTrimClipEnd,
  notifyWorkspaceTrimClipStart,
} from '../infrastructure/workspaceApi';

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

/**
 * Merge a Rust workspace snapshot over the current store workspace.
 *
 * Local-only UI state (playhead, zoom, volume, mute, playing, marker,
 * selection) is preserved per file; the locally polled LPR runtime status is
 * preserved as well. Unknown remote files start from domain defaults.
 */
function applySyncedWorkspace(
  current: EditorWorkspaceState,
  remote: EditorWorkspacePayload,
): EditorWorkspaceState {
  const nextFiles = remote.files.map((remoteFile) => {
    const localFile = current.files.find(
      (f) => f.id === remoteFile.id || f.asset.path === remoteFile.asset.path || f.asset.id === remoteFile.asset.id,
    );
    if (!localFile) {
      return {
        ...remoteFile,
        playheadMs: 0,
        zoom: DEFAULT_ZOOM,
        previewVolume: 0.85,
        previewMuted: false,
        isPlaying: false,
        markerRect: null,
        selectedClipIds: [],
      };
    }
    return {
      ...remoteFile,
      id: remoteFile.id,
      playheadMs: localFile.playheadMs,
      zoom: localFile.zoom ?? DEFAULT_ZOOM,
      previewVolume: localFile.previewVolume,
      previewMuted: localFile.previewMuted,
      isPlaying: localFile.isPlaying,
      markerRect: localFile.markerRect,
      selectedClipIds: localFile.selectedClipIds,
    };
  });
  return {
    ...remote,
    files: nextFiles,
    // We preserve the local LPR runtime status since it's locally polled.
    analysis: {
      ...remote.analysis,
      lprRuntimeStatus: current.analysis.lprRuntimeStatus,
    },
  };
}

function commitSyncedPayload(remote: RustEditorWorkspaceState): void {
  const store = useEditorStore.getState();
  store.commitWorkspace(applySyncedWorkspace(store.workspace, toEditorWorkspacePayload(remote)));
}

/**
 * Mount-once Rust ↔ store session sync (Phase 3-C).
 *
 * Fetches the initial app state from Rust and subscribes to
 * `editor/state-updated`, committing merged snapshots into the Zustand
 * session slice. Mount in `MainWorkspace`; the revision/version semantics
 * are owned by the session slice (`commitWorkspace`).
 */
export function useEditorSessionSync(): void {
  useEffect(() => {
    // 1. Fetch initial state from Rust (via infrastructure API)
    fetchAppState()
      .then((data) => {
        commitSyncedPayload(data);
      })
      .catch((error) => {
        console.error('Failed to get initial app state from Rust:', error);
      });

    // 2. Listen to state updates from Rust
    const unlisten = listen<RustEditorWorkspaceState>('editor/state-updated', (event) => {
      commitSyncedPayload(event.payload);
    });

    return () => {
      unlisten.then((f) => f());
    };
  }, []);
}

/**
 * Workspace mutations that must stay synchronized with the Rust backend
 * (Phase 7: commands moved into the infrastructure API per Blueprint §2.2).
 *
 * Each entry applies the optimistic store update first, then notifies Rust
 * through the infrastructure API (fire-and-forget; backend failures are
 * logged there). Local-only state (zoom, selection, preview, LPR/AI
 * sessions) is intentionally absent here — callers use the Zustand store
 * actions directly for those.
 */
export const editorWorkspaceTransport = {
  addFiles(assets: EditorAsset[]): void {
    useEditorStore.getState().addFiles(assets);
    void notifyWorkspaceAddFiles(assets);
  },

  removeFile(fileId: string): void {
    useEditorStore.getState().removeFile(fileId);
    void notifyWorkspaceRemoveFile(fileId);
  },

  setActiveFile(fileId: string): void {
    useEditorStore.getState().setActiveFile(fileId);
    void notifyWorkspaceSetActiveFile(fileId);
  },

  moveClip(clipId: string, startMs: number): void {
    const currentWorkspace = useEditorStore.getState().workspace;
    useEditorStore.getState().moveClip(clipId, startMs);
    const fileId = currentWorkspace.activeFileId;
    if (fileId) {
      void notifyWorkspaceMoveClip(fileId, clipId, startMs);
    }
  },

  trimClipStart(clipId: string, inPointMs: number): void {
    const currentWorkspace = useEditorStore.getState().workspace;
    useEditorStore.getState().trimClipStart(clipId, inPointMs);
    const fileId = currentWorkspace.activeFileId;
    if (fileId) {
      const clip = currentWorkspace.files.find((f) => f.id === fileId)?.clips.find((c) => c.id === clipId);
      if (clip) {
        const newStartMs = clip.startMs + (inPointMs - clip.inPointMs);
        void notifyWorkspaceTrimClipStart(fileId, clipId, inPointMs, newStartMs);
      }
    }
  },

  trimClipEnd(clipId: string, outPointMs: number): void {
    const currentWorkspace = useEditorStore.getState().workspace;
    useEditorStore.getState().trimClipEnd(clipId, outPointMs);
    const fileId = currentWorkspace.activeFileId;
    if (fileId) {
      void notifyWorkspaceTrimClipEnd(fileId, clipId, outPointMs);
    }
  },

  splitClip(clipId: string, atMs: number): void {
    const currentWorkspace = useEditorStore.getState().workspace;
    useEditorStore.getState().splitClip(clipId, atMs);
    const fileId = currentWorkspace.activeFileId;
    if (fileId) {
      void notifyWorkspaceSplitClip(fileId, clipId, atMs);
    }
  },

  deleteSelectedClips(): void {
    const currentWorkspace = useEditorStore.getState().workspace;
    useEditorStore.getState().deleteSelectedClips();
    const file = currentWorkspace.files.find((f) => f.id === currentWorkspace.activeFileId);
    if (file) {
      void notifyWorkspaceDeleteClips(file.id, file.selectedClipIds);
    }
  },

  setSelectedClipsMuted(muted: boolean): void {
    const currentWorkspace = useEditorStore.getState().workspace;
    useEditorStore.getState().setSelectedClipsMuted(muted);
    const file = currentWorkspace.files.find((f) => f.id === currentWorkspace.activeFileId);
    if (file) {
      void notifyWorkspaceSetClipsMuted(file.id, file.selectedClipIds, muted);
    }
  },

  setRenderProfile(renderProfile: Partial<RenderProfile>): void {
    const currentWorkspace = useEditorStore.getState().workspace;
    useEditorStore.getState().setRenderProfile(renderProfile);
    const file = currentWorkspace.files.find((f) => f.id === currentWorkspace.activeFileId);
    if (file) {
      void notifyWorkspaceSetRenderProfile(file.id, renderProfile, file.renderProfile);
    }
  },
};
