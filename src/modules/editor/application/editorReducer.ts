import type {
  EditorAsset,
  EditorWorkspaceState,
  LprFrameSample,
  LprJobState,
  LprPlateCandidate,
  LprResultHistoryEntry,
  LprSessionState,
  LprTargetTrack,
  LprVehicleKind,
  LprWorkflowMode,
  TimelineIntervalSelection,
  VideoMarkerRect,
} from '../domain/model';
import {
  buildDefaultWorkspaceState,
  buildDefaultLprState,
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
  | { type: 'clear-marker' }
  | { type: 'set-lpr-mode'; workflowMode: LprWorkflowMode }
  | { type: 'set-lpr-interval'; interval: TimelineIntervalSelection }
  | { type: 'clear-lpr-interval' }
  | { type: 'set-lpr-target-vehicle-kind'; targetVehicleKind: LprVehicleKind }
  | { type: 'set-lpr-country-hints'; countryHints: string[] }
  | {
      type: 'set-lpr-toggles';
      toggles: Partial<Pick<LprSessionState, 'useDenseSampling'>>;
    }
  | { type: 'set-lpr-target-tracks'; targetTracks: LprTargetTrack[] }
  | { type: 'select-lpr-target-track'; targetTrackId: string | null }
  | { type: 'set-lpr-job'; job: Partial<LprJobState> }
  | { type: 'set-lpr-samples'; samples: LprFrameSample[] }
  | { type: 'set-lpr-candidates'; candidates: LprPlateCandidate[] }
  | { type: 'accept-lpr-candidate'; candidateId: string | null }
  | { type: 'append-lpr-history'; entry: LprResultHistoryEntry }
  | { type: 'clear-lpr-results' }
  | { type: 'reset-lpr-session' };

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

function mapActiveLprState(
  state: EditorWorkspaceState,
  updater: (lprState: LprSessionState) => LprSessionState,
) {
  return updateActiveFile(state, (fileState) => ({
    ...fileState,
    lpr: updater(fileState.lpr),
  }));
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
      return updateActiveFile(state, (fileState) => {
        if (
          fileState.selectedClipIds.length === action.clipIds.length
          && fileState.selectedClipIds.every((clipId, index) => clipId === action.clipIds[index])
        ) {
          return fileState;
        }

        return {
          ...fileState,
          selectedClipIds: action.clipIds,
        };
      });

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

    case 'set-lpr-mode':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        workflowMode: action.workflowMode,
      }));

    case 'set-lpr-interval':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        interval: {
          startMs: Math.max(0, Math.min(action.interval.startMs, action.interval.endMs)),
          endMs: Math.max(0, Math.max(action.interval.startMs, action.interval.endMs)),
        },
        workflowMode: lprState.workflowMode === 'idle' ? 'range' : lprState.workflowMode,
      }));

    case 'clear-lpr-interval':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        interval: null,
      }));

    case 'set-lpr-target-vehicle-kind':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        targetVehicleKind: action.targetVehicleKind,
      }));

    case 'set-lpr-country-hints':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        countryHints: [...action.countryHints],
      }));

    case 'set-lpr-toggles':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        ...action.toggles,
      }));

    case 'set-lpr-target-tracks':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        targetTracks: buildDefaultLprState({ targetTracks: action.targetTracks }).targetTracks,
        selectedTargetTrackId: action.targetTracks.some((track) => track.id === lprState.selectedTargetTrackId)
          ? lprState.selectedTargetTrackId
          : action.targetTracks[0]?.id ?? null,
      }));

    case 'select-lpr-target-track':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        selectedTargetTrackId: action.targetTrackId,
        workflowMode: action.targetTrackId ? 'target' : lprState.workflowMode,
      }));

    case 'set-lpr-job':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        job: {
          ...lprState.job,
          ...action.job,
        },
      }));

    case 'set-lpr-samples':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        samples: buildDefaultLprState({ samples: action.samples }).samples,
      }));

    case 'set-lpr-candidates':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        candidates: buildDefaultLprState({ candidates: action.candidates }).candidates,
        acceptedCandidateId: action.candidates.some((candidate) => candidate.id === lprState.acceptedCandidateId)
          ? lprState.acceptedCandidateId
          : action.candidates[0]?.id ?? null,
      }));

    case 'accept-lpr-candidate':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        acceptedCandidateId: action.candidateId,
        workflowMode: action.candidateId ? 'review' : lprState.workflowMode,
      }));

    case 'append-lpr-history':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        history: [...lprState.history, buildDefaultLprState({ history: [action.entry] }).history[0]],
      }));

    case 'clear-lpr-results':
      return mapActiveLprState(state, (lprState) => ({
        ...lprState,
        job: buildDefaultLprState().job,
        targetTracks: [],
        selectedTargetTrackId: null,
        samples: [],
        candidates: [],
        acceptedCandidateId: null,
      }));

    case 'reset-lpr-session':
      return mapActiveLprState(state, () => buildDefaultLprState());

    default:
      return state;
  }
}

export const initialEditorState = buildDefaultWorkspaceState();