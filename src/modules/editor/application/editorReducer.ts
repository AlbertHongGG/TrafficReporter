import type { EditorAsset, EditorWorkspaceState, VideoMarkerRect } from '../domain/model';
import {
  buildDefaultWorkspaceState,
  buildEditorFileState,
  clamp,
  getActiveFile,
  MAX_ZOOM,
  MIN_ZOOM,
  normalizeMarkerRect,
} from '../domain/model';
import {
  deleteSelectedClips,
  moveClip,
  relinkFileAsset,
  setTrackMuted,
  setSelectedClipMuted,
  splitClipAt,
  trimClipEnd,
  trimClipStart,
} from '../domain/timelineCommands';

export type EditorAction =
  | { type: 'reset-workspace' }
  | { type: 'add-files'; assets: EditorAsset[] }
  | { type: 'remove-file'; fileId: string }
  | { type: 'set-active-file'; fileId: string }
  | { type: 'relink-file'; fileId: string; asset: EditorAsset }
  | { type: 'set-selection'; clipIds: string[] }
  | { type: 'move-clip'; clipId: string; startMs: number }
  | { type: 'trim-clip-start'; clipId: string; inPointMs: number }
  | { type: 'trim-clip-end'; clipId: string; outPointMs: number }
  | { type: 'split-clip'; clipId: string; atMs: number }
  | { type: 'delete-selected-clips' }
  | { type: 'set-selected-clips-muted'; muted: boolean }
  | { type: 'set-track-muted'; muted: boolean }
  | { type: 'set-playhead'; playheadMs: number }
  | { type: 'set-playing'; isPlaying: boolean }
  | { type: 'set-zoom'; zoom: number }
  | { type: 'set-preview-volume'; previewVolume: number }
  | { type: 'set-preview-muted'; previewMuted: boolean }
  | { type: 'set-marker-rect'; markerRect: VideoMarkerRect }
  | { type: 'clear-marker' };

export function createInitialEditorState() {
  return buildDefaultWorkspaceState();
}

function mapFiles(state: EditorWorkspaceState, mapper: (fileState: EditorWorkspaceState['files'][number]) => EditorWorkspaceState['files'][number]) {
  let changed = false;
  const files = state.files.map((fileState) => {
    const nextFileState = mapper(fileState);
    if (nextFileState !== fileState) {
      changed = true;
    }
    return nextFileState;
  });

  if (!changed) {
    return state;
  }

  return {
    ...state,
    files,
  };
}

function updateActiveFile(state: EditorWorkspaceState, updater: (fileState: EditorWorkspaceState['files'][number]) => EditorWorkspaceState['files'][number]) {
  const activeFile = getActiveFile(state);
  if (!activeFile) {
    return state;
  }

  return mapFiles(
    state,
    (fileState) => (fileState.id === activeFile.id ? updater(fileState) : fileState),
  );
}

function stopPlaybackForAllFiles(files: EditorWorkspaceState['files']) {
  return files.map((fileState) => (fileState.isPlaying ? { ...fileState, isPlaying: false } : fileState));
}

export function editorReducer(state: EditorWorkspaceState, action: EditorAction): EditorWorkspaceState {
  switch (action.type) {
    case 'reset-workspace':
      return buildDefaultWorkspaceState();

    case 'add-files': {
      const existingPaths = new Set(state.files.map((fileState) => fileState.asset.path));
      const nextFiles = action.assets
        .filter((asset) => !existingPaths.has(asset.path))
        .map((asset) => buildEditorFileState(asset));
      if (nextFiles.length === 0) {
        return state;
      }

      return {
        ...state,
        files: [...state.files, ...nextFiles],
        activeFileId: nextFiles.at(-1)?.id ?? state.activeFileId,
      };
    }

    case 'remove-file': {
      const removingIndex = state.files.findIndex((fileState) => fileState.id === action.fileId);
      if (removingIndex === -1) {
        return state;
      }

      const nextFiles = state.files.filter((fileState) => fileState.id !== action.fileId);
      const fallbackIndex = Math.min(removingIndex, nextFiles.length - 1);
      return {
        ...state,
        files: nextFiles,
        activeFileId: nextFiles.length === 0
          ? null
          : state.activeFileId === action.fileId
            ? nextFiles[Math.max(0, fallbackIndex)]?.id ?? null
            : state.activeFileId,
      };
    }

    case 'set-active-file': {
      if (!state.files.some((fileState) => fileState.id === action.fileId) || state.activeFileId === action.fileId) {
        return state;
      }

      return {
        ...state,
        activeFileId: action.fileId,
        files: stopPlaybackForAllFiles(state.files),
      };
    }

    case 'relink-file':
      return mapFiles(
        state,
        (fileState) => (fileState.id === action.fileId ? relinkFileAsset(fileState, action.asset) : fileState),
      );

    case 'set-selection':
      return updateActiveFile(state, (fileState) => ({
        ...fileState,
        selectedClipIds: action.clipIds,
      }));

    case 'move-clip':
      return updateActiveFile(state, (fileState) => moveClip(fileState, action.clipId, action.startMs));

    case 'trim-clip-start':
      return updateActiveFile(state, (fileState) => trimClipStart(fileState, action.clipId, action.inPointMs));

    case 'trim-clip-end':
      return updateActiveFile(state, (fileState) => trimClipEnd(fileState, action.clipId, action.outPointMs));

    case 'split-clip':
      return updateActiveFile(state, (fileState) => splitClipAt(fileState, action.clipId, action.atMs));

    case 'delete-selected-clips':
      return updateActiveFile(state, deleteSelectedClips);

    case 'set-selected-clips-muted':
      return updateActiveFile(state, (fileState) => setSelectedClipMuted(fileState, action.muted));

    case 'set-track-muted':
      return updateActiveFile(state, (fileState) => setTrackMuted(fileState, action.muted));

    case 'set-playhead':
      return updateActiveFile(state, (fileState) => ({
        ...fileState,
        playheadMs: Math.max(0, action.playheadMs),
      }));

    case 'set-playing':
      return updateActiveFile(state, (fileState) => ({
        ...fileState,
        isPlaying: action.isPlaying,
      }));

    case 'set-zoom':
      return updateActiveFile(state, (fileState) => ({
        ...fileState,
        zoom: clamp(action.zoom, MIN_ZOOM, MAX_ZOOM),
      }));

    case 'set-preview-volume':
      return updateActiveFile(state, (fileState) => ({
        ...fileState,
        previewVolume: clamp(action.previewVolume, 0, 1),
      }));

    case 'set-preview-muted':
      return updateActiveFile(state, (fileState) => ({
        ...fileState,
        previewMuted: action.previewMuted,
      }));

    case 'set-marker-rect':
      return updateActiveFile(
        state,
        (fileState) => ({
          ...fileState,
          markerRect: normalizeMarkerRect(action.markerRect),
        }),
      );

    case 'clear-marker':
      return updateActiveFile(
        state,
        (fileState) => ({
          ...fileState,
          markerRect: null,
        }),
      );

    default:
      return state;
  }
}

export const initialEditorState = buildDefaultWorkspaceState();