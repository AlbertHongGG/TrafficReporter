import type { StateCreator } from 'zustand';
import {
  buildDefaultWorkspaceState,
  buildEditorFileState,
  clamp,
  getActiveFile,
  MAX_ZOOM,
  MIN_ZOOM,
  normalizeMarkerRect,
} from '../../domain/model';
import type {
  EditorAsset,
  EditorFileState,
  EditorWorkspaceState,
  RenderProfile,
  VideoMarkerRect,
} from '../../domain/model';
import { pruneAnalysisSessions } from '../../domain/analysisState';
import {
  deleteSelectedClips,
  moveClip,
  relinkFileAsset,
  setSelectedClipMuted,
  setTrackMuted,
  splitClipAt,
  trimClipEnd,
  trimClipStart,
} from '../../domain/timelineCommands';
import type { EditorStore } from './store';

/**
 * Intentionally field-free: every timeline/playback UI state (selected clips,
 * playhead, zoom, volume, marker, …) lives per-file inside `workspace`, which
 * is owned by the session slice. This slice contributes the timeline action
 * surface only. The named type is kept so every slice follows one uniform
 * `State & Actions` shape for the Wave 2 assembly.
 */
export interface TimelineState {
  // No owned fields.
}

export interface TimelineActions {
  addFiles: (assets: EditorAsset[]) => void;
  removeFile: (fileId: string) => void;
  setActiveFile: (fileId: string) => void;
  relinkFile: (fileId: string, asset: EditorAsset) => void;
  setSelection: (clipIds: string[]) => void;
  moveClip: (clipId: string, startMs: number) => void;
  trimClipStart: (clipId: string, inPointMs: number) => void;
  trimClipEnd: (clipId: string, outPointMs: number) => void;
  splitClip: (clipId: string, atMs: number) => void;
  deleteSelectedClips: () => void;
  setSelectedClipsMuted: (muted: boolean) => void;
  setTrackMuted: (muted: boolean) => void;
  setPlayhead: (playheadMs: number) => void;
  setPlaying: (isPlaying: boolean) => void;
  setZoom: (zoom: number) => void;
  setPreviewVolume: (previewVolume: number) => void;
  setPreviewMuted: (previewMuted: boolean) => void;
  setRenderProfile: (renderProfile: Partial<RenderProfile>) => void;
  setMarkerRect: (markerRect: VideoMarkerRect) => void;
  clearMarker: () => void;
  resetWorkspace: () => void;
}

export type TimelineSlice = TimelineState & TimelineActions;

type TimelineSliceCreator = StateCreator<EditorStore, [], [], TimelineSlice>;

type FileState = EditorWorkspaceState['files'][number];

function mapFiles(
  workspace: EditorWorkspaceState,
  mapper: (fileState: FileState) => FileState,
): EditorWorkspaceState {
  let changed = false;
  const files = workspace.files.map((fileState) => {
    const nextFileState = mapper(fileState);
    if (nextFileState !== fileState) {
      changed = true;
    }
    return nextFileState;
  });

  if (!changed) {
    return workspace;
  }

  return {
    ...workspace,
    files,
  };
}

function updateActiveFile(
  workspace: EditorWorkspaceState,
  updater: (fileState: FileState) => FileState,
): EditorWorkspaceState {
  const activeFile = getActiveFile(workspace);
  if (!activeFile) {
    return workspace;
  }

  return mapFiles(
    workspace,
    (fileState) => (fileState.id === activeFile.id ? updater(fileState) : fileState),
  );
}

function stopPlaybackForAllFiles(files: EditorFileState[]): EditorFileState[] {
  return files.map((fileState) => (fileState.isPlaying ? { ...fileState, isPlaying: false } : fileState));
}

/** Pure action creators below: each maps a workspace to the next workspace. */

/** Append new file states for assets whose path is not already present. */
export function applyAddFiles(
  workspace: EditorWorkspaceState,
  assets: EditorAsset[],
): EditorWorkspaceState {
  const existingPaths = new Set(workspace.files.map((fileState) => fileState.asset.path));
  const nextFiles = assets
    .filter((asset) => !existingPaths.has(asset.path))
    .map((asset) => buildEditorFileState(asset));
  if (nextFiles.length === 0) {
    return workspace;
  }

  return {
    ...workspace,
    files: [...workspace.files, ...nextFiles],
    activeFileId: nextFiles.at(-1)?.id ?? workspace.activeFileId,
  };
}

/** Remove a file and prune its orphaned analysis sessions. */
export function applyRemoveFile(
  workspace: EditorWorkspaceState,
  fileId: string,
): EditorWorkspaceState {
  const removingIndex = workspace.files.findIndex((fileState) => fileState.id === fileId);
  if (removingIndex === -1) {
    return workspace;
  }

  const nextFiles = workspace.files.filter((fileState) => fileState.id !== fileId);
  const fallbackIndex = Math.min(removingIndex, nextFiles.length - 1);
  return {
    ...workspace,
    files: nextFiles,
    analysis: pruneAnalysisSessions(
      workspace.analysis,
      nextFiles.map((fileState) => fileState.id),
    ),
    activeFileId: nextFiles.length === 0
      ? null
      : workspace.activeFileId === fileId
        ? nextFiles[Math.max(0, fallbackIndex)]?.id ?? null
        : workspace.activeFileId,
  };
}

/** Activate a file and stop playback everywhere else. */
export function applySetActiveFile(
  workspace: EditorWorkspaceState,
  fileId: string,
): EditorWorkspaceState {
  if (!workspace.files.some((fileState) => fileState.id === fileId) || workspace.activeFileId === fileId) {
    return workspace;
  }

  return {
    ...workspace,
    activeFileId: fileId,
    files: stopPlaybackForAllFiles(workspace.files),
  };
}

/** Swap the underlying asset of a file, sanitizing its clips. */
export function applyRelinkFile(
  workspace: EditorWorkspaceState,
  fileId: string,
  asset: EditorAsset,
): EditorWorkspaceState {
  return mapFiles(
    workspace,
    (fileState) => (fileState.id === fileId ? relinkFileAsset(fileState, asset) : fileState),
  );
}

/** Replace the active file's clip selection (same order + ids = no-op). */
export function applySelection(
  workspace: EditorWorkspaceState,
  clipIds: string[],
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => {
    if (
      fileState.selectedClipIds.length === clipIds.length
      && fileState.selectedClipIds.every((clipId, index) => clipId === clipIds[index])
    ) {
      return fileState;
    }

    return {
      ...fileState,
      selectedClipIds: clipIds,
    };
  });
}

/** Move a clip along the active file's track (snapping + de-overlap inside). */
export function applyMoveClip(
  workspace: EditorWorkspaceState,
  clipId: string,
  startMs: number,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => moveClip(fileState, clipId, startMs));
}

/** Trim a clip's head. */
export function applyTrimClipStart(
  workspace: EditorWorkspaceState,
  clipId: string,
  inPointMs: number,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => trimClipStart(fileState, clipId, inPointMs));
}

/** Trim a clip's tail. */
export function applyTrimClipEnd(
  workspace: EditorWorkspaceState,
  clipId: string,
  outPointMs: number,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => trimClipEnd(fileState, clipId, outPointMs));
}

/** Split a clip at a timeline time; the right half becomes the selection. */
export function applySplitClip(
  workspace: EditorWorkspaceState,
  clipId: string,
  atMs: number,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => splitClipAt(fileState, clipId, atMs));
}

/** Delete the active file's selected clips. */
export function applyDeleteSelectedClips(workspace: EditorWorkspaceState): EditorWorkspaceState {
  return updateActiveFile(workspace, deleteSelectedClips);
}

/** Mute/unmute the active file's selected clips. */
export function applySetSelectedClipsMuted(
  workspace: EditorWorkspaceState,
  muted: boolean,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => setSelectedClipMuted(fileState, muted));
}

/** Mute/unmute every clip of the active file. */
export function applySetTrackMuted(
  workspace: EditorWorkspaceState,
  muted: boolean,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => setTrackMuted(fileState, muted));
}

/** Move the active file's playhead (floored at 0). */
export function applyPlayhead(
  workspace: EditorWorkspaceState,
  playheadMs: number,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => ({
    ...fileState,
    playheadMs: Math.max(0, playheadMs),
  }));
}

/** Toggle playback on the active file. */
export function applyPlaying(
  workspace: EditorWorkspaceState,
  isPlaying: boolean,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => ({
    ...fileState,
    isPlaying,
  }));
}

/** Set the active file's zoom, clamped to the domain range. */
export function applyZoom(workspace: EditorWorkspaceState, zoom: number): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => ({
    ...fileState,
    zoom: clamp(zoom, MIN_ZOOM, MAX_ZOOM),
  }));
}

/** Set the active file's preview volume, clamped to [0, 1]. */
export function applyPreviewVolume(
  workspace: EditorWorkspaceState,
  previewVolume: number,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => ({
    ...fileState,
    previewVolume: clamp(previewVolume, 0, 1),
  }));
}

/** Toggle the active file's preview mute flag. */
export function applyPreviewMuted(
  workspace: EditorWorkspaceState,
  previewMuted: boolean,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => ({
    ...fileState,
    previewMuted,
  }));
}

/** Merge a partial render profile into the active file (no-op when equal). */
export function applyRenderProfile(
  workspace: EditorWorkspaceState,
  renderProfile: Partial<RenderProfile>,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => {
    const hasChange = Object.entries(renderProfile).some(([key, value]) => (
      fileState.renderProfile[key as keyof typeof fileState.renderProfile] !== value
    ));
    if (!hasChange) {
      return fileState;
    }

    return {
      ...fileState,
      renderProfile: {
        ...fileState.renderProfile,
        ...renderProfile,
      },
    };
  });
}

/** Set the active file's marker rect (normalized into unit space). */
export function applyMarkerRect(
  workspace: EditorWorkspaceState,
  markerRect: VideoMarkerRect,
): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => ({
    ...fileState,
    markerRect: normalizeMarkerRect(markerRect),
  }));
}

/** Clear the active file's marker. */
export function applyClearMarker(workspace: EditorWorkspaceState): EditorWorkspaceState {
  return updateActiveFile(workspace, (fileState) => ({
    ...fileState,
    markerRect: null,
  }));
}

/** Replace the workspace with a fresh default. */
export function applyResetWorkspace(): EditorWorkspaceState {
  return buildDefaultWorkspaceState();
}

export const createTimelineSlice: TimelineSliceCreator = (_set, get) => {
  const commit = (nextWorkspace: EditorWorkspaceState): void => {
    get().commitWorkspace(nextWorkspace);
  };

  return {
    addFiles: (assets) => {
      commit(applyAddFiles(get().workspace, assets));
    },
    removeFile: (fileId) => {
      commit(applyRemoveFile(get().workspace, fileId));
    },
    setActiveFile: (fileId) => {
      commit(applySetActiveFile(get().workspace, fileId));
    },
    relinkFile: (fileId, asset) => {
      commit(applyRelinkFile(get().workspace, fileId, asset));
    },
    setSelection: (clipIds) => {
      commit(applySelection(get().workspace, clipIds));
    },
    moveClip: (clipId, startMs) => {
      commit(applyMoveClip(get().workspace, clipId, startMs));
    },
    trimClipStart: (clipId, inPointMs) => {
      commit(applyTrimClipStart(get().workspace, clipId, inPointMs));
    },
    trimClipEnd: (clipId, outPointMs) => {
      commit(applyTrimClipEnd(get().workspace, clipId, outPointMs));
    },
    splitClip: (clipId, atMs) => {
      commit(applySplitClip(get().workspace, clipId, atMs));
    },
    deleteSelectedClips: () => {
      commit(applyDeleteSelectedClips(get().workspace));
    },
    setSelectedClipsMuted: (muted) => {
      commit(applySetSelectedClipsMuted(get().workspace, muted));
    },
    setTrackMuted: (muted) => {
      commit(applySetTrackMuted(get().workspace, muted));
    },
    setPlayhead: (playheadMs) => {
      commit(applyPlayhead(get().workspace, playheadMs));
    },
    setPlaying: (isPlaying) => {
      commit(applyPlaying(get().workspace, isPlaying));
    },
    setZoom: (zoom) => {
      commit(applyZoom(get().workspace, zoom));
    },
    setPreviewVolume: (previewVolume) => {
      commit(applyPreviewVolume(get().workspace, previewVolume));
    },
    setPreviewMuted: (previewMuted) => {
      commit(applyPreviewMuted(get().workspace, previewMuted));
    },
    setRenderProfile: (renderProfile) => {
      commit(applyRenderProfile(get().workspace, renderProfile));
    },
    setMarkerRect: (markerRect) => {
      commit(applyMarkerRect(get().workspace, markerRect));
    },
    clearMarker: () => {
      commit(applyClearMarker(get().workspace));
    },
    resetWorkspace: () => {
      commit(applyResetWorkspace());
    },
  };
};
