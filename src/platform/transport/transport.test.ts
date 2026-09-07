import { describe, expect, it } from 'vitest';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  AI_PANEL_SESSION_UPDATED_EVENT,
  AI_PANEL_WINDOW_LABEL,
} from '../../modules/editor/application/aiPanelWindow';
import { buildDefaultAiEvidenceState } from '../../modules/editor/domain/aiEvidenceState';
import { buildDefaultLprState } from '../../modules/editor/domain/lprState';
import type {
  AiPanelSessionSnapshot,
} from '../../modules/editor/application/aiPanelWindow';
import type {
  PlateWindowSessionSnapshot,
} from '../../modules/editor/application/plateWindow';
import {
  PLATE_ACTION_EVENT,
  PLATE_LIVE_TRANSPORT_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  PLATE_SESSION_UPDATED_EVENT,
  PLATE_WINDOW_LABEL,
} from '../../modules/editor/application/plateWindow';
import {
  EXPORT_SESSION_REQUEST_EVENT,
  EXPORT_SESSION_UPDATED_EVENT,
  EXPORT_WINDOW_LABEL,
} from '../../modules/export/application/exportWindow';
import type { ExportSnapshot } from '../../modules/export/application/exportTypes';
import type { DesktopWindowId } from '../desktop/windowConfigs';
import {
  aiPanelContract,
  errorReport,
  exportContract,
  plateContract,
  transportContracts,
} from './contracts';
import {
  parseTransportEnvelope,
  registerErrorListener,
  registerListener,
  requestSession,
  sendAction,
  sendError,
  sendLive,
  sendSession,
  TransportContractError,
  TransportDirectionError,
  type TransportBackend,
} from './runtime';
import {
  isWindowErrorReport,
  isWorkspaceRuntimeSnapshot,
  type WindowErrorReport,
  type WorkspaceRuntimeSnapshot,
} from './types';

interface SentCall {
  readonly method: 'broadcast' | 'send' | 'sendToMain';
  readonly target: DesktopWindowId | null;
  readonly event: string;
  readonly payload: unknown;
  readonly version: number | null;
}

interface FakeTransport {
  readonly backend: TransportBackend;
  readonly calls: SentCall[];
  readonly emitRaw: (event: string, payload: unknown) => void;
}

/**
 * 注入的假 emit/listen：只替換 transport 後端，不 mock 整個 tauri。
 * broadcast 按既有 desktopWindowManager 語義包 VersionedPayload；
 * send / sendToMain 按既有語義投遞原始 payload。
 */
function createFakeTransport(): FakeTransport {
  const calls: SentCall[] = [];
  const handlers = new Map<string, Array<(payload: unknown) => void>>();

  const deliver = (event: string, payload: unknown): void => {
    const list = handlers.get(event) ?? [];
    for (const handler of list) {
      handler(payload);
    }
  };

  const backend: TransportBackend = {
    broadcast: (target, event, payload, version = 0) => {
      calls.push({ method: 'broadcast', target, event, payload, version });
      deliver(event, {
        version,
        timestamp: '2026-09-07T00:00:00.000Z',
        payload,
      });
      return Promise.resolve();
    },
    send: (target, event, payload) => {
      calls.push({ method: 'send', target, event, payload, version: null });
      deliver(event, payload);
      return Promise.resolve();
    },
    sendToMain: (event, payload) => {
      calls.push({ method: 'sendToMain', target: 'main', event, payload, version: null });
      deliver(event, payload);
      return Promise.resolve();
    },
    listen: <T>(event: string, handler: (payload: T) => void): Promise<() => void> => {
      const wrapped = (payload: unknown): void => {
        handler(payload as T);
      };
      const list = handlers.get(event) ?? [];
      list.push(wrapped);
      handlers.set(event, list);
      return Promise.resolve(() => {
        const current = handlers.get(event) ?? [];
        handlers.set(
          event,
          current.filter((entry) => entry !== wrapped),
        );
      });
    },
  };

  return { backend, calls, emitRaw: deliver };
}

function buildPlateSnapshot(playheadMs: number): PlateWindowSessionSnapshot {
  return {
    workspaceName: 'workspace',
    activeFileName: 'clip.mp4',
    hasActiveFile: true,
    runtimeStatus: null,
    lpr: buildDefaultLprState(),
    explicitInterval: null,
    effectiveInterval: null,
    canAnalyzeRange: false,
    topCandidate: null,
    anchorTimeMs: playheadMs,
    playheadMs,
  };
}

function buildAiSnapshot(): AiPanelSessionSnapshot {
  return {
    workspaceName: 'workspace',
    activeFileName: 'clip.mp4',
    hasActiveFile: true,
    runtimeStatus: null,
    lpr: buildDefaultLprState(),
    ai: buildDefaultAiEvidenceState(),
    playheadMs: 0,
  };
}

function buildExportSnapshot(): ExportSnapshot {
  return {
    workspaceName: 'workspace',
    activeFileName: 'clip.mp4',
    hasActiveFile: true,
    runtimeStatus: null,
    playheadMs: 0,
    fileId: 'file-1',
    fileName: 'clip.mp4',
    suggestedName: 'timeline-export',
    timelineDurationMs: 1000,
    hasVideo: true,
    hasAudio: false,
    sources: [],
    tracks: [],
    clips: [],
    renderProfile: { format: 'mp4', fps: 30, compressionMode: 'standard' },
  };
}

describe('transport contracts — wire 表', () => {
  it('plate 契約沿用既有字串與方向', () => {
    expect(plateContract.windowLabel).toBe(PLATE_WINDOW_LABEL);
    expect(plateContract.event.event).toBe(PLATE_SESSION_UPDATED_EVENT);
    expect(plateContract.requestEvent.event).toBe(PLATE_SESSION_REQUEST_EVENT);
    expect(plateContract.actionEvent?.event).toBe(PLATE_ACTION_EVENT);
    expect(plateContract.liveEvent?.event).toBe(PLATE_LIVE_TRANSPORT_EVENT);
    expect(plateContract.event.direction).toBe('main-to-window');
    expect(plateContract.requestEvent.direction).toBe('window-to-main');
    expect(plateContract.actionEvent?.direction).toBe('window-to-main');
    expect(plateContract.liveEvent?.direction).toBe('main-to-window');
    expect(plateContract.direction).toBe('both');
  });

  it('ai-panel 契約沿用既有字串且無 live 通道', () => {
    expect(aiPanelContract.windowLabel).toBe(AI_PANEL_WINDOW_LABEL);
    expect(aiPanelContract.event.event).toBe(AI_PANEL_SESSION_UPDATED_EVENT);
    expect(aiPanelContract.requestEvent.event).toBe(AI_PANEL_SESSION_REQUEST_EVENT);
    expect(aiPanelContract.actionEvent?.event).toBe(AI_PANEL_ACTION_EVENT);
    expect(aiPanelContract.liveEvent).toBeNull();
    expect(aiPanelContract.direction).toBe('both');
  });

  it('export 契約沿用既有字串、無 action 通道、live 為 export-progress', () => {
    expect(exportContract.windowLabel).toBe(EXPORT_WINDOW_LABEL);
    expect(exportContract.event.event).toBe(EXPORT_SESSION_UPDATED_EVENT);
    expect(exportContract.requestEvent.event).toBe(EXPORT_SESSION_REQUEST_EVENT);
    expect(exportContract.actionEvent).toBeNull();
    expect(exportContract.liveEvent?.event).toBe('editor/export-progress');
    expect(exportContract.liveEvent?.direction).toBe('main-to-window');
  });

  it('契約表收齊三視窗且錯誤通道為新事件、不與既有事件重疊', () => {
    expect(Object.keys(transportContracts).sort()).toEqual(['aiPanel', 'export', 'plate']);
    expect(errorReport.direction).toBe('window-to-main');
    const wireEvents = [
      plateContract.event.event,
      plateContract.requestEvent.event,
      plateContract.actionEvent?.event,
      plateContract.liveEvent?.event,
      aiPanelContract.event.event,
      aiPanelContract.requestEvent.event,
      aiPanelContract.actionEvent?.event,
      exportContract.event.event,
      exportContract.requestEvent.event,
      exportContract.liveEvent?.event,
    ];
    expect(wireEvents).not.toContain(errorReport.event);
    expect(new Set(wireEvents).size).toBe(wireEvents.length);
  });
});

describe('transport runtime — 版本仲裁', () => {
  it('新版本套用、過期版本拒收、同版本套用', async () => {
    const fake = createFakeTransport();
    const received: PlateWindowSessionSnapshot[] = [];
    await registerListener(plateContract.event, (data) => {
      received.push(data);
    }, fake.backend);

    await sendSession(plateContract, buildPlateSnapshot(100), 3, fake.backend);
    await sendSession(plateContract, buildPlateSnapshot(50), 2, fake.backend);
    await sendSession(plateContract, buildPlateSnapshot(300), 3, fake.backend);

    expect(received.map((snapshot) => snapshot.playheadMs)).toEqual([100, 300]);
  });

  it('相容舊 { revision, snapshot } 包絡與無包絡原始 payload', async () => {
    const fake = createFakeTransport();
    const received: PlateWindowSessionSnapshot[] = [];
    await registerListener(plateContract.event, (data) => {
      received.push(data);
    }, fake.backend);

    fake.emitRaw(plateContract.event.event, {
      revision: 4,
      snapshot: buildPlateSnapshot(400),
    });
    expect(received).toHaveLength(1);
    expect(received[0]?.playheadMs).toBe(400);

    const aiReceived: AiPanelSessionSnapshot[] = [];
    await registerListener(aiPanelContract.event, (data) => {
      aiReceived.push(data);
    }, fake.backend);
    fake.emitRaw(aiPanelContract.event.event, buildAiSnapshot());
    expect(aiReceived).toHaveLength(1);
  });

  it('parseTransportEnvelope 逐字保留舊解析語義', () => {
    const versioned = parseTransportEnvelope<PlateWindowSessionSnapshot>({
      version: 7,
      timestamp: 'ts',
      payload: buildPlateSnapshot(7),
    });
    expect(versioned.version).toBe(7);
    expect(versioned.data.playheadMs).toBe(7);

    const legacy = parseTransportEnvelope<PlateWindowSessionSnapshot>({
      revision: 5,
      snapshot: buildPlateSnapshot(5),
    });
    expect(legacy.version).toBe(5);
    expect(legacy.data.playheadMs).toBe(5);

    const raw = parseTransportEnvelope<PlateWindowSessionSnapshot>(buildPlateSnapshot(9));
    expect(raw.version).toBe(0);
    expect(raw.data.playheadMs).toBe(9);

    const malformed = parseTransportEnvelope<PlateWindowSessionSnapshot>({
      version: 'oops',
      payload: buildPlateSnapshot(1),
    });
    expect(malformed.version).toBe(0);
  });

  it('unlisten 後不再投遞', async () => {
    const fake = createFakeTransport();
    let count = 0;
    const unlisten = await registerListener(
      exportContract.event,
      () => {
        count += 1;
      },
      fake.backend,
    );
    await sendSession(exportContract, buildExportSnapshot(), 1, fake.backend);
    unlisten();
    await sendSession(exportContract, buildExportSnapshot(), 2, fake.backend);
    expect(count).toBe(1);
  });
});

describe('transport runtime — 錯誤通道可達', () => {
  it('sendError 經 sendToMain 投遞 { ok:false, code, reason }', async () => {
    const fake = createFakeTransport();
    await sendError(
      {
        code: 'ANALYZE_FRAME_FAILED',
        reason: 'engine offline',
        sourceWindow: 'plate',
        actionType: 'analyze-frame',
      },
      fake.backend,
    );

    expect(fake.calls).toHaveLength(1);
    const call = fake.calls[0];
    expect(call?.method).toBe('sendToMain');
    expect(call?.event).toBe(errorReport.event);
    const payload = call?.payload;
    expect(isWindowErrorReport(payload)).toBe(true);
    const report = payload as WindowErrorReport;
    expect(report.ok).toBe(false);
    expect(report.code).toBe('ANALYZE_FRAME_FAILED');
    expect(report.reason).toBe('engine offline');
    expect(report.sourceWindow).toBe('plate');
    expect(report.actionType).toBe('analyze-frame');
  });

  it('主視窗錯誤監聽收到合法回報、忽略畸形 payload', async () => {
    const fake = createFakeTransport();
    const received: WindowErrorReport[] = [];
    await registerErrorListener((report) => {
      received.push(report);
    }, fake.backend);

    await sendError({ code: 'E1', reason: 'r1', sourceWindow: 'export' }, fake.backend);
    fake.emitRaw(errorReport.event, { ok: true, code: 'E2' });
    fake.emitRaw(errorReport.event, null);

    expect(received).toHaveLength(1);
    expect(received[0]?.actionType).toBeNull();
  });
});

describe('transport runtime — directional 發送', () => {
  it('session 走 broadcast 到對應視窗與事件（含版本）', async () => {
    const fake = createFakeTransport();
    await sendSession(aiPanelContract, buildAiSnapshot(), 6, fake.backend);
    expect(fake.calls).toEqual([
      {
        method: 'broadcast',
        target: 'ai-panel',
        event: 'editor/ai-panel-session-updated',
        payload: expect.anything(),
        version: 6,
      },
    ]);
  });

  it('action 與 request 走 sendToMain 到各自事件', async () => {
    const fake = createFakeTransport();
    await sendAction(plateContract, { type: 'refresh-runtime' }, fake.backend);
    await requestSession(plateContract.requestEvent, fake.backend);

    expect(fake.calls.map((call) => [call.method, call.event])).toEqual([
      ['sendToMain', 'editor/plate-action'],
      ['sendToMain', 'editor/plate-session-request'],
    ]);
    expect(fake.calls[1]?.payload).toBeNull();
  });

  it('live 走 send 到對應視窗（非版本化）', async () => {
    const fake = createFakeTransport();
    await sendLive(
      plateContract,
      { playheadMs: 120, mode: 'playing', updatedAt: 'ts' },
      fake.backend,
    );
    expect(fake.calls).toHaveLength(1);
    expect(fake.calls[0]?.method).toBe('send');
    expect(fake.calls[0]?.target).toBe('plate');
    expect(fake.calls[0]?.event).toBe('editor/plate-live-transport');
  });

  it('缺失通道與錯誤方向拋結構化錯誤', async () => {
    const fake = createFakeTransport();
    expect(() => sendAction(exportContract, null, fake.backend)).toThrow(TransportContractError);
    expect(() => sendLive(aiPanelContract, null, fake.backend)).toThrow(TransportContractError);

    const flipped = {
      ...plateContract,
      event: { event: plateContract.event.event, direction: 'window-to-main' as const },
    };
    expect(() => sendSession(flipped, buildPlateSnapshot(0), 1, fake.backend)).toThrow(
      TransportDirectionError,
    );
    expect(fake.calls).toHaveLength(0);
  });
});

describe('transport types — 共用快照守衛', () => {
  it('WorkspaceRuntimeSnapshot 守衛收斂 runtimeStatus＋playheadMs＋transport 層級', () => {
    const snapshot: WorkspaceRuntimeSnapshot = {
      workspaceName: 'workspace',
      activeFileName: null,
      hasActiveFile: false,
      runtimeStatus: null,
      playheadMs: 0,
      liveTransport: null,
    };
    expect(isWorkspaceRuntimeSnapshot(snapshot)).toBe(true);
    expect(isWorkspaceRuntimeSnapshot({ workspaceName: 'w' })).toBe(false);
    expect(isWorkspaceRuntimeSnapshot(null)).toBe(false);
  });
});
