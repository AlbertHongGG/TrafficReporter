import { describe, expect, it } from 'vitest';

import { buildDefaultWorkspaceState, buildEditorFileState } from '../../editor/domain/model';
import { preparePendingExportSession } from './exportSession';

describe('preparePendingExportSession', () => {
  it('carries the active file render profile into the export snapshot', () => {
    const state = buildDefaultWorkspaceState();
    const fileState = buildEditorFileState({
      id: 'asset-1',
      name: 'camera-a.mp4',
      path: 'C:/media/camera-a.mp4',
      kind: 'video',
      durationMs: 8000,
      hasVideo: true,
      hasAudio: true,
      fps: 30,
      audioBitrateKbps: 192,
      width: 3840,
      height: 2160,
      status: 'ready',
      url: 'asset://camera-a.mp4',
      thumbnailUrl: null,
    });

    fileState.renderProfile = {
      format: 'mp4',
      fps: 120,
      videoQuality: '2160p',
      audioBitrateKbps: 320,
      compressionMode: 'compact',
    };
    fileState.clips = [
      {
        id: 'clip-1',
        assetId: 'asset-1',
        trackId: fileState.track.id,
        startMs: 500,
        inPointMs: 1000,
        outPointMs: 4000,
        muted: false,
      },
    ];

    state.workspaceName = 'Interview Cut';
    state.files = [fileState];
    state.activeFileId = fileState.id;

    const snapshot = preparePendingExportSession(state);

    expect(snapshot.fileId).toBe(fileState.id);
    expect(snapshot.fileName).toBe('camera-a.mp4');
    expect(snapshot.renderProfile).toEqual(fileState.renderProfile);
    expect(snapshot.timelineDurationMs).toBe(3500);
    expect(snapshot.dominantWidth).toBe(3840);
    expect(snapshot.sources).toHaveLength(1);
  });

  it('rejects exports while the active file is missing', () => {
    const state = buildDefaultWorkspaceState();
    const fileState = buildEditorFileState({
      id: 'asset-1',
      name: 'missing.mp4',
      path: 'C:/media/missing.mp4',
      kind: 'video',
      durationMs: 4000,
      hasVideo: true,
      hasAudio: true,
      fps: 30,
      audioBitrateKbps: 192,
      width: 1920,
      height: 1080,
      status: 'missing',
      url: null,
      thumbnailUrl: null,
    });

    state.files = [fileState];
    state.activeFileId = fileState.id;

    expect(() => preparePendingExportSession(state)).toThrow('Relink missing media before exporting');
  });
});
