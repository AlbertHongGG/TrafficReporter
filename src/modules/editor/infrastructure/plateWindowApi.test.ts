import { describe, expect, it } from 'vitest';

import { buildDefaultLprState } from '../domain/lprState';
import {
  PLATE_ACTION_EVENT,
  PLATE_LIVE_TRANSPORT_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  PLATE_SESSION_UPDATED_EVENT,
  PLATE_WINDOW_LABEL,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';
import { plateContract } from '../../../platform/transport/contracts';
import type { TransportBackend } from '../../../platform/transport/runtime';
import type { DesktopWindowId } from '../../../platform/desktop/windowConfigs';
import {
  emitPlateWindowLiveTransport,
  emitPlateWindowSession,
  requestPlateWindowSession,
  sendPlateWindowAction,
} from './plateWindowApi';

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

function buildSnapshot(playheadMs: number): PlateWindowSessionSnapshot {
  return {
    workspaceName: 'Traffic',
    activeFileName: 'demo.mp4',
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

describe('plateWindowApi — 全經 transport runtime（plateContract）', () => {
  it('wire 事件名字串不變且契約指向 plate 視窗', () => {
    expect(PLATE_SESSION_UPDATED_EVENT).toBe('editor/plate-session-updated');
    expect(PLATE_SESSION_REQUEST_EVENT).toBe('editor/plate-session-request');
    expect(PLATE_ACTION_EVENT).toBe('editor/plate-action');
    expect(PLATE_LIVE_TRANSPORT_EVENT).toBe('editor/plate-live-transport');
    expect(plateContract.event.event).toBe(PLATE_SESSION_UPDATED_EVENT);
    expect(plateContract.requestEvent.event).toBe(PLATE_SESSION_REQUEST_EVENT);
    expect(plateContract.actionEvent?.event).toBe(PLATE_ACTION_EVENT);
    expect(plateContract.liveEvent?.event).toBe(PLATE_LIVE_TRANSPORT_EVENT);
    expect(plateContract.windowLabel).toBe(PLATE_WINDOW_LABEL);
  });

  it('emit session 走 broadcast 到 plate（含版本）', async () => {
    const calls: SentCall[] = [];
    await emitPlateWindowSession(buildSnapshot(100), 3, createFakeBackend(calls));
    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe('broadcast');
    expect(calls[0]?.target).toBe('plate');
    expect(calls[0]?.event).toBe('editor/plate-session-updated');
    expect(calls[0]?.version).toBe(3);
    expect((calls[0]?.payload as PlateWindowSessionSnapshot).playheadMs).toBe(100);
  });

  it('emit live 走 send 到 plate（非版本化）', async () => {
    const calls: SentCall[] = [];
    await emitPlateWindowLiveTransport(
      { playheadMs: 120, mode: 'playing', updatedAt: '2026-09-07T00:00:00.000Z' },
      createFakeBackend(calls),
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe('send');
    expect(calls[0]?.target).toBe('plate');
    expect(calls[0]?.event).toBe('editor/plate-live-transport');
  });

  it('request 與 action 走 sendToMain 到各自事件', async () => {
    const calls: SentCall[] = [];
    const backend = createFakeBackend(calls);
    await requestPlateWindowSession(backend);
    await sendPlateWindowAction({ type: 'analyze-frame' }, backend);
    expect(calls.map((call) => [call.method, call.event])).toEqual([
      ['sendToMain', 'editor/plate-session-request'],
      ['sendToMain', 'editor/plate-action'],
    ]);
    expect(calls[0]?.payload).toBeNull();
  });
});
