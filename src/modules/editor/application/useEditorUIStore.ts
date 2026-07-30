import { useState, useCallback } from 'react';
import type { VideoMarkerRect } from '../domain/model';
import { DEFAULT_ZOOM } from '../domain/model';

export interface FileUIState {
  selectedClipIds: string[];
  playheadMs: number;
  zoom: number;
  previewVolume: number;
  previewMuted: boolean;
  isPlaying: boolean;
  markerRect: VideoMarkerRect | null;
}

export const DEFAULT_FILE_UI_STATE: FileUIState = {
  selectedClipIds: [],
  playheadMs: 0,
  zoom: DEFAULT_ZOOM,
  previewVolume: 0.85,
  previewMuted: false,
  isPlaying: false,
  markerRect: null,
};

export function useEditorUIStore() {
  const [uiStates, setUIStates] = useState<Record<string, FileUIState>>({});

  const getUIState = useCallback((fileId: string | null): FileUIState => {
    if (!fileId) return DEFAULT_FILE_UI_STATE;
    return uiStates[fileId] || DEFAULT_FILE_UI_STATE;
  }, [uiStates]);

  const updateUIState = useCallback((fileId: string, updates: Partial<FileUIState>) => {
    setUIStates((prev) => ({
      ...prev,
      [fileId]: {
        ...(prev[fileId] || DEFAULT_FILE_UI_STATE),
        ...updates,
      },
    }));
  }, []);

  return {
    getUIState,
    updateUIState,
  };
}
