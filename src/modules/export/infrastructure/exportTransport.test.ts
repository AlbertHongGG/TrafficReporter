import { describe, expect, it } from 'vitest';

import {
  EXPORT_SESSION_REQUEST_EVENT,
  EXPORT_SESSION_UPDATED_EVENT,
  EXPORT_WINDOW_LABEL,
} from '../application/exportWindow';
import type { ExportSnapshot } from '../application/exportTypes';
import { buildDefaultWorkspaceState, buildEditorFileState } from '../../editor/domain/model';
import { preparePendingExportSession } from '../application/exportSession';
import { exportContract } from '../../../platform/transport/contracts';
import { isWorkspaceRuntimeSnapshot } from '../../../platform/transport/types';
import type { TransportBackend } from '../../../platform/transport/runtime';
import type { DesktopWindowId } from '../../../platform/desktop/windowConfigs';
import { requestExportWindowSession, syncExportWindowSession } from './exportApi';

interface SentCall {
  readonly method: 'broadcast' | 'send' | 'sendToMain';
  readonly target: DesktopWindowId | null;
  readonly event: string;
  readonly payload: unknown;
  readonly version: number | null;
}

function createFakeBackend(calls: SentCall[]): TransportBackend {
  return {
    broadcast: (target, event, payload, version = 0) => {
      calls.push({ method: 'broadcast', target, event, payload, version });
      return Promise.resolve();
    },
    send: (target, event, payload) => {
      calls.push({ method: 'send', target, event, payload, version: null });
      return Promise.resolve();
    },
    sendToMain: (event, payload) => {
      calls.push({ method: 'sendToMain', target: 'main', event, payload, version: null });
      return Promise.resolve();
    },
    listen: () => Promise.resolve(() => undefined),
  };
}

function buildExportableState() {
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
    width: 1920,
    height: 1080,
    status: 'ready',
    url: 'asset://camera-a.mp4',
    thumbnailUrl: null,
  });
  fileState.clips = [
    {
      id: 'clip-1',
      assetId: 'asset-1',
      trackId: fileState.track.id,
      startMs: 0,
      inPointMs: 0,
      outPointMs: 2000,
      muted: false,
    },
  ];
  state.workspaceName = 'Interview Cut';
  state.files = [fileState];
  state.activeFileId = fileState.id;
  return state;
}

/**
 * Phase 5-D 絞殺門檻：export 走 exportContract、wire 不變、快照收斂、
 * 傳輸函式全經 transport runtime。對應 B/C 的 plate / ai-panel 鎖定。
 */
describe('export transport contract — Phase 5-D 絞殺', () => {
  it('契約沿用既有字串、無 action 通道、live 為 export-progress', () => {
    expect(EXPORT_SESSION_UPDATED_EVENT).toBe('editor/export-session-updated');
    expect(EXPORT_SESSION_REQUEST_EVENT).toBe('editor/export-session-request');
    expect(exportContract.windowLabel).toBe(EXPORT_WINDOW_LABEL);
    expect(exportContract.event.event).toBe(EXPORT_SESSION_UPDATED_EVENT);
    expect(exportContract.requestEvent.event).toBe(EXPORT_SESSION_REQUEST_EVENT);
    expect(exportContract.actionEvent).toBeNull();
    expect(exportContract.liveEvent?.event).toBe('editor/export-progress');
    expect(exportContract.event.direction).toBe('main-to-window');
    expect(exportContract.requestEvent.direction).toBe('window-to-main');
  });

  it('快照收斂到 WorkspaceRuntimeSnapshot＋export 自身欄位', () => {
    const state = buildExportableState();
    const snapshot = preparePendingExportSession(state);
    expect(snapshot.workspaceName).toBe('Interview Cut');
    expect(snapshot.activeFileName).toBe('camera-a.mp4');
    expect(snapshot.hasActiveFile).toBe(true);
    expect(snapshot.runtimeStatus).toBeNull();
    expect(snapshot.playheadMs).toBe(0);
    expect(isWorkspaceRuntimeSnapshot({ ...snapshot, liveTransport: null })).toBe(true);
    const own: ExportSnapshot = snapshot;
    expect(own.fileId).toBe(state.files[0]?.id);
    expect(own.fileName).toBe('camera-a.mp4');
    expect(own.clips).toHaveLength(1);
    expect(own.renderProfile).toBeDefined();
  });

  it('sync 走 broadcast 到 export（含版本）、request 走 sendToMain', async () => {
    const calls: SentCall[] = [];
    const backend = createFakeBackend(calls);
    const state = buildExportableState();
    const snapshot = preparePendingExportSession(state);
    const expectedFileId = state.files[0]?.id;

    await syncExportWindowSession(snapshot, 4, backend);
    await requestExportWindowSession(backend);

    expect(calls.map((call) => [call.method, call.event])).toEqual([
      ['broadcast', 'editor/export-session-updated'],
      ['sendToMain', 'editor/export-session-request'],
    ]);
    expect(calls[0]?.target).toBe('export');
    expect(calls[0]?.version).toBe(4);
    expect((calls[0]?.payload as ExportSnapshot).fileId).toBe(expectedFileId);
    expect(calls[1]?.payload).toBeNull();
  });
});
