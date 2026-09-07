import { describe, expect, it } from 'vitest';
import { create } from 'zustand';
import { cloneValue, cloneWorkspaceState, StoreCloneError } from './clone';
import {
  applyAddFiles,
  applyClearMarker,
  applyDeleteSelectedClips,
  applyMarkerRect,
  applyMoveClip,
  applyPlayhead,
  applyPlaying,
  applyPreviewMuted,
  applyPreviewVolume,
  applyRemoveFile,
  applyRenderProfile,
  applySelection,
  applySetActiveFile,
  applySetSelectedClipsMuted,
  applySetTrackMuted,
  applySplitClip,
  applyTrimClipEnd,
  applyZoom,
} from './timelineSlice';
import { createTimelineSlice } from './timelineSlice';
import { createUiSlice } from './uiSlice';
import { applyWorkspaceName } from './uiSlice';
import { createLprSlice } from './lprSlice';
import { createAiSlice } from './aiSlice';
import { commitWorkspaceState, createInitialSessionState, createSessionSlice } from './sessionSlice';
import { buildDefaultWorkspaceState } from '../../domain/model';
import type { EditorAsset, EditorWorkspaceState } from '../../domain/model';
import { getActiveFile } from '../../domain/model';
import { useEditorStore, type EditorStore } from './store';

function makeAsset(id: string, path: string): EditorAsset {
  return {
    id,
    name: `${id}.mp4`,
    path,
    url: null,
    thumbnailUrl: null,
    hasVideo: true,
    hasAudio: true,
    durationMs: 8000,
    fps: 30,
    audioBitrateKbps: 192,
    width: 1920,
    height: 1080,
    kind: 'video',
  };
}

function workspaceWithFile(): EditorWorkspaceState {
  return applyAddFiles(buildDefaultWorkspaceState(), [makeAsset('asset-1', 'C:/media/a.mp4')]);
}

function createTestStore() {
  return create<EditorStore>()((...a) => ({
    ...createTimelineSlice(...a),
    ...createUiSlice(...a),
    ...createSessionSlice(...a),
    ...createLprSlice(...a),
    ...createAiSlice(...a),
  }));
}

describe('store/clone', () => {
  it('deep-copies values so later mutations stay isolated', () => {
    const workspace = workspaceWithFile();
    const snapshot = cloneWorkspaceState(workspace);

    expect(snapshot).toEqual(workspace);
    expect(snapshot).not.toBe(workspace);
    expect(snapshot.files[0]).not.toBe(workspace.files[0]);
    expect(snapshot.files[0]?.asset).not.toBe(workspace.files[0]?.asset);

    snapshot.files[0]?.clips.push({
      id: 'clip-evil',
      assetId: 'asset-1',
      trackId: 'track-x',
      startMs: 0,
      inPointMs: 0,
      outPointMs: 120,
      muted: false,
    });
    expect(workspace.files[0]?.clips.some((clip) => clip.id === 'clip-evil')).toBe(false);
  });

  it('throws a structured StoreCloneError for non-cloneable values', () => {
    const throwing = (): void => {
      cloneValue({ handler: () => undefined }, 'workspace/files');
    };

    expect(throwing).toThrow(StoreCloneError);
    try {
      throwing();
      expect.unreachable('cloneValue should have thrown');
    } catch (error: unknown) {
      expect(error).toBeInstanceOf(StoreCloneError);
      if (error instanceof StoreCloneError) {
        expect(error.code).toBe('CLONE_FAILED');
        expect(error.path).toBe('workspace/files');
        expect(error.reason.length).toBeGreaterThan(0);
      }
    }
  });
});

describe('store/timelineSlice pure action creators', () => {
  it('adds files, ignores duplicate paths, and activates the last file', () => {
    const empty = buildDefaultWorkspaceState();
    const withOne = applyAddFiles(empty, [makeAsset('asset-1', 'C:/media/a.mp4')]);

    expect(withOne.files).toHaveLength(1);
    expect(withOne.activeFileId).toBe(withOne.files[0]?.id);
    expect(getActiveFile(withOne)?.clips).toHaveLength(1);

    const duplicate = applyAddFiles(withOne, [makeAsset('asset-9', 'C:/media/a.mp4')]);
    expect(duplicate).toBe(withOne);
  });

  it('sets and clears selection with reference-equality fast paths', () => {
    const workspace = workspaceWithFile();
    const clipId = workspace.files[0]?.clips[0]?.id ?? '';
    const selected = applySelection(workspace, [clipId]);

    expect(getActiveFile(selected)?.selectedClipIds).toEqual([clipId]);
    expect(applySelection(selected, [clipId])).toBe(selected);
  });

  it('clamps playhead, zoom, and preview volume into domain ranges', () => {
    const workspace = workspaceWithFile();

    expect(getActiveFile(applyPlayhead(workspace, -50))?.playheadMs).toBe(0);
    expect(getActiveFile(applyPlayhead(workspace, 1234))?.playheadMs).toBe(1234);
    expect(getActiveFile(applyZoom(workspace, 99999))?.zoom).toBe(2400);
    expect(getActiveFile(applyZoom(workspace, -5))?.zoom).toBe(0.5);
    expect(getActiveFile(applyPreviewVolume(workspace, 7))?.previewVolume).toBe(1);
    expect(getActiveFile(applyPlaying(workspace, true))?.isPlaying).toBe(true);
    expect(getActiveFile(applyPreviewMuted(workspace, true))?.previewMuted).toBe(true);
  });

  it('normalizes marker rects and clears them', () => {
    const workspace = workspaceWithFile();
    const marked = applyMarkerRect(workspace, { x: -1, y: 2, width: 10, height: 10 });

    expect(getActiveFile(marked)?.markerRect).toMatchObject({ x: 0, y: 1 });
    expect(getActiveFile(applyClearMarker(marked))?.markerRect).toBeNull();
  });

  it('moves, splits, mutes, trims, and deletes clips through domain commands', () => {
    const workspace = workspaceWithFile();
    const clipId = workspace.files[0]?.clips[0]?.id ?? '';

    const moved = applyMoveClip(workspace, clipId, 1000);
    expect(moved.files[0]?.clips[0]?.startMs).toBe(1000);
    expect(applyMoveClip(workspace, 'missing-clip', 1000)).toBe(workspace);

    const split = applySplitClip(moved, clipId, 1500);
    expect(split.files[0]?.clips).toHaveLength(2);
    expect(split.files[0]?.selectedClipIds).toHaveLength(1);

    const muted = applySetSelectedClipsMuted(split, true);
    const selectedId = muted.files[0]?.selectedClipIds[0] ?? '';
    expect(muted.files[0]?.clips.find((clip) => clip.id === selectedId)?.muted).toBe(true);

    const trackMuted = applySetTrackMuted(workspace, true);
    expect(trackMuted.files[0]?.clips.every((clip) => clip.muted)).toBe(true);

    const trimmed = applyTrimClipEnd(workspace, clipId, 4000);
    expect(trimmed.files[0]?.clips[0]?.outPointMs).toBe(4000);

    const withSelection = applySelection(workspace, [clipId]);
    expect(applyDeleteSelectedClips(withSelection).files[0]?.clips).toHaveLength(0);
    expect(applyDeleteSelectedClips(workspace)).toBe(workspace);
  });

  it('merges render-profile patches and ignores no-change patches', () => {
    const workspace = workspaceWithFile();
    const patched = applyRenderProfile(workspace, { fps: 24 });

    expect(getActiveFile(patched)?.renderProfile.fps).toBe(24);
    expect(applyRenderProfile(patched, { fps: 24 })).toBe(patched);
  });

  it('removes files and keeps unknown removals / activations as no-ops', () => {
    const workspace = applyAddFiles(workspaceWithFile(), [makeAsset('asset-2', 'C:/media/b.mp4')]);
    const removedId = workspace.files[0]?.id ?? '';
    const removed = applyRemoveFile(workspace, removedId);

    expect(removed.files).toHaveLength(1);
    expect(removed.activeFileId).toBe(workspace.files[1]?.id);
    expect(applyRemoveFile(workspace, 'missing-file')).toBe(workspace);
    expect(applySetActiveFile(workspace, 'missing-file')).toBe(workspace);
    expect(applySetActiveFile(workspace, workspace.activeFileId ?? '')).toBe(workspace);
  });
});

describe('store/sessionSlice revision semantics', () => {
  it('starts at revision 0 and bumps only when the workspace reference changes', () => {
    const initial = createInitialSessionState(buildDefaultWorkspaceState(), 't0');

    expect(initial.revision).toBe(0);
    expect(initial.updatedAt).toBe('t0');

    expect(commitWorkspaceState(initial, initial.workspace, 't1')).toBe(initial);

    const next = commitWorkspaceState(initial, applyPlayhead(workspaceWithFile(), 500), 't1');
    expect(next.revision).toBe(1);
    expect(next.updatedAt).toBe('t1');
  });

  it('keeps store revision still when committing the same workspace reference', () => {
    const store = createTestStore();
    store.getState().addFiles([makeAsset('asset-1', 'C:/media/a.mp4')]);
    const revision = store.getState().revision;

    store.getState().commitWorkspace(store.getState().workspace);
    expect(store.getState().revision).toBe(revision);
  });
});

describe('store/uiSlice', () => {
  it('pushes feedback copies and clears them', () => {
    const store = createTestStore();
    store.getState().pushFeedback({ scope: 'import', message: 'hello' });

    expect(store.getState().lastFeedback).toEqual({ scope: 'import', message: 'hello' });

    store.getState().clearFeedback();
    expect(store.getState().lastFeedback).toBeNull();
  });

  it('renames the workspace through pure helper with revision bumps on change only', () => {
    const workspace = workspaceWithFile();
    expect(applyWorkspaceName(workspace, workspace.workspaceName)).toBe(workspace);

    const store = createTestStore();
    store.getState().addFiles([makeAsset('asset-1', 'C:/media/a.mp4')]);
    const revision = store.getState().revision;

    store.getState().setWorkspaceName(store.getState().workspace.workspaceName);
    expect(store.getState().revision).toBe(revision);

    store.getState().setWorkspaceName('Renamed');
    expect(store.getState().workspace.workspaceName).toBe('Renamed');
    expect(store.getState().revision).toBe(revision + 1);
  });
});

describe('store assembly', () => {
  it('combines timeline, ui, and session slices with revision-per-write', () => {
    const store = createTestStore();
    expect(store.getState().revision).toBe(0);

    store.getState().addFiles([makeAsset('asset-1', 'C:/media/a.mp4')]);
    expect(store.getState().revision).toBe(1);

    const clipId = store.getState().workspace.files[0]?.clips[0]?.id ?? '';
    store.getState().setSelection([clipId]);
    store.getState().setPlayhead(250);
    expect(store.getState().revision).toBe(3);
    expect(getActiveFile(store.getState().workspace)?.playheadMs).toBe(250);

    store.getState().setActiveFile('missing-file');
    expect(store.getState().revision).toBe(3);
  });

  it('exposes the composed singleton with all slice actions', () => {
    const state = useEditorStore.getState();

    expect(state.revision).toBe(0);
    expect(state.lastFeedback).toBeNull();
    expect(typeof state.addFiles).toBe('function');
    expect(typeof state.setPlayhead).toBe('function');
    expect(typeof state.pushFeedback).toBe('function');
    expect(typeof state.commitWorkspace).toBe('function');
  });
});
