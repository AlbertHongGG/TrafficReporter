import { create } from 'zustand';
import { createSessionSlice, type SessionSlice } from './sessionSlice';
import { createTimelineSlice, type TimelineSlice } from './timelineSlice';
import { createUiSlice, type UiSlice } from './uiSlice';
import { createLprSlice, type LprSlice } from './lprSlice';
import { createAiSlice, type AiSlice } from './aiSlice';

/**
 * Phase 3 editor store (Zustand v5): all five slices composed.
 *
 * React reads and writes exclusively through `useEditorStore` selectors;
 * the session slice owns the workspace, revision, and updated-at versioning
 * for cross-window sync.
 */
export type EditorStore = TimelineSlice & UiSlice & SessionSlice & LprSlice & AiSlice;

export const useEditorStore = create<EditorStore>()((...a) => ({
  ...createTimelineSlice(...a),
  ...createUiSlice(...a),
  ...createSessionSlice(...a),
  ...createLprSlice(...a),
  ...createAiSlice(...a),
}));
