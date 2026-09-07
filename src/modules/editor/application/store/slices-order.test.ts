import { describe, expect, it } from 'vitest';
import { create } from 'zustand';
import { createSessionSlice } from './sessionSlice';
import { createTimelineSlice } from './timelineSlice';
import { createUiSlice } from './uiSlice';
import { applySetLprMode, createLprSlice } from './lprSlice';
import { applySetAiResult, createAiSlice } from './aiSlice';
import { buildDefaultWorkspaceState, getActiveFile } from '../../domain/model';
import type { EditorAsset } from '../../domain/model';
import {
  getAiEvidenceSessionByFileId,
  getLprSessionByFileId,
} from '../../domain/analysisState';
import { buildDefaultLprState } from '../../domain/lprState';
import type { EditorStore } from './store';

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

function createTestStore() {
  return create<EditorStore>()((...a) => ({
    ...createTimelineSlice(...a),
    ...createUiSlice(...a),
    ...createSessionSlice(...a),
    ...createLprSlice(...a),
    ...createAiSlice(...a),
  }));
}

describe('store/slices-order', () => {
  it('bumps revision monotonically across three different slices (revision = 3)', () => {
    const store = createTestStore();
    expect(store.getState().revision).toBe(0);

    store.getState().addFiles([makeAsset('asset-a', 'C:/media/a.mp4')]);
    expect(store.getState().revision).toBe(1);

    store.getState().setLprMode('range');
    expect(store.getState().revision).toBe(2);

    const fileId = store.getState().workspace.activeFileId ?? '';
    store.getState().setAiPrompt(fileId, 'describe the plate');
    expect(store.getState().revision).toBe(3);
  });

  it('keeps lpr/ai/timeline writes consistent when interleaved', () => {
    const store = createTestStore();
    store.getState().addFiles([makeAsset('asset-a', 'C:/media/a.mp4')]);
    const fileId = store.getState().workspace.activeFileId ?? '';

    store.getState().setPlayhead(1200);
    store.getState().setLprInterval({ startMs: 1000, endMs: 2400 });
    store.getState().setAiJob(fileId, { status: 'running', progress: 0.5 });
    store.getState().setLprCandidates([]);
    store.getState().setPlayhead(2500);

    const state = store.getState();
    // 1 (addFiles) + 5 interleaved writes = 6.
    expect(state.revision).toBe(6);
    expect(getActiveFile(state.workspace)?.playheadMs).toBe(2500);
    expect(getLprSessionByFileId(state.workspace.analysis, fileId).interval).toEqual({
      startMs: 1000,
      endMs: 2400,
    });
    expect(getAiEvidenceSessionByFileId(state.workspace.analysis, fileId).job.status).toBe('running');
    // Timeline writes must not wipe the LPR session written in between.
    expect(getLprSessionByFileId(state.workspace.analysis, fileId).workflowMode).toBe('range');
  });

  it('isolates per-file sessions: fileA writes do not pollute fileB', () => {
    const store = createTestStore();
    store.getState().addFiles([
      makeAsset('asset-a', 'C:/media/a.mp4'),
      makeAsset('asset-b', 'C:/media/b.mp4'),
    ]);
    const files = store.getState().workspace.files;
    const fileA = files[0]?.id ?? '';
    const fileB = files[1]?.id ?? '';

    store.getState().setActiveFile(fileA);
    store.getState().setLprMode('target');
    store.getState().setAiPrompt(fileA, 'prompt for A');

    store.getState().setActiveFile(fileB);
    const state = store.getState();

    expect(getLprSessionByFileId(state.workspace.analysis, fileB).workflowMode).toBe('idle');
    expect(getAiEvidenceSessionByFileId(state.workspace.analysis, fileB).prompt).toBe('');
    expect(getLprSessionByFileId(state.workspace.analysis, fileA).workflowMode).toBe('target');
    expect(getAiEvidenceSessionByFileId(state.workspace.analysis, fileA).prompt).toBe('prompt for A');
  });

  it('stays consistent when a timeline write follows replace-lpr-session', () => {
    const store = createTestStore();
    store.getState().addFiles([makeAsset('asset-a', 'C:/media/a.mp4')]);
    const fileId = store.getState().workspace.activeFileId ?? '';
    const revisionAfterAdd = store.getState().revision;

    store.getState().replaceLprSession(fileId, buildDefaultLprState({ workflowMode: 'target' }));
    expect(store.getState().revision).toBe(revisionAfterAdd + 1);

    store.getState().setPlayhead(777);
    const state = store.getState();
    expect(state.revision).toBe(revisionAfterAdd + 2);
    expect(getActiveFile(state.workspace)?.playheadMs).toBe(777);
    expect(getLprSessionByFileId(state.workspace.analysis, fileId).workflowMode).toBe('target');
  });

  it('does not bump revision when an lpr write has no active file (same reference)', () => {
    const empty = buildDefaultWorkspaceState();
    expect(applySetLprMode(empty, 'range')).toBe(empty);

    const store = createTestStore();
    store.getState().setLprMode('range');
    expect(store.getState().revision).toBe(0);
  });

  it('keeps lastCompletedAt untouched when clearing an ai result with null', () => {
    const store = createTestStore();
    store.getState().addFiles([makeAsset('asset-a', 'C:/media/a.mp4')]);
    const fileId = store.getState().workspace.activeFileId ?? '';

    const workspace = store.getState().workspace;
    const stamped = applySetAiResult(workspace, fileId, null, 't-stamp');
    // Null result never stamps: still a new workspace (session entry created)
    // but the timestamp stays null.
    expect(getAiEvidenceSessionByFileId(stamped.analysis, fileId).lastCompletedAt).toBeNull();
    expect(stamped).not.toBe(workspace);
  });
});
