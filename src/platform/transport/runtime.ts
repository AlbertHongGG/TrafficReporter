import { listen as tauriListen } from '@tauri-apps/api/event';
import { desktopWindowManager } from '../desktop/DesktopWindowManager';
import { shouldApplyVersion } from '../desktop/desktopSync';
import type { DesktopWindowId } from '../desktop/windowConfigs';
import { errorReport, type ContractChannel, type TransportDirection, type WindowContract } from './contracts';
import {
  createWindowErrorReport,
  isWindowErrorReport,
  type WindowErrorReport,
} from './types';

/**
 * Transport runtime（Blueprint §5.3，Phase 5-A）。
 *
 * registerListener / send 封裝：version 檢查、結構化錯誤通道、
 * 底層走既有 desktopWindowManager（broadcast / send / sendToMain）與
 * tauri emit-listen。雙通道不互寫 snapshot 的約束由呼叫端（Wave D 的
 * coordinator 聲明式重寫）維持；本單元只提供方向檢查的發送原語。
 */

/** 可注入的傳輸後端：預設走既有 desktopWindowManager＋tauri listen；測試注入假實作。 */
export interface TransportBackend {
  broadcast<T>(
    targetWindowLabel: DesktopWindowId,
    event: string,
    payload: T,
    version?: number,
  ): Promise<void>;
  sendToMain<T>(event: string, payload: T): Promise<void>;
  send<T>(targetWindowLabel: DesktopWindowId, event: string, payload: T): Promise<void>;
  listen<T>(event: string, handler: (payload: T) => void): Promise<() => void>;
}

export const defaultTransportBackend: TransportBackend = {
  broadcast: <T>(
    targetWindowLabel: DesktopWindowId,
    event: string,
    payload: T,
    version = 0,
  ): Promise<void> => desktopWindowManager.broadcast(targetWindowLabel, event, payload, version),
  sendToMain: <T>(event: string, payload: T): Promise<void> =>
    desktopWindowManager.sendToMain(event, payload),
  send: <T>(targetWindowLabel: DesktopWindowId, event: string, payload: T): Promise<void> =>
    desktopWindowManager.send(targetWindowLabel, event, payload),
  listen: <T>(event: string, handler: (payload: T) => void): Promise<() => void> =>
    tauriListen<T>(event, (tauriEvent) => {
      handler(tauriEvent.payload);
    }),
};

export class TransportDirectionError extends Error {
  constructor(event: string, expected: TransportDirection, actual: TransportDirection) {
    super(`Transport channel "${event}" flows ${actual}; this sender requires ${expected}.`);
    this.name = 'TransportDirectionError';
  }
}

export class TransportContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TransportContractError';
  }
}

function requireDirection<TPayload>(
  channel: ContractChannel<TPayload>,
  expected: TransportDirection,
): void {
  if (channel.direction !== expected && channel.direction !== 'both') {
    throw new TransportDirectionError(channel.event, expected, channel.direction);
  }
}

export interface ParsedTransportEnvelope<T> {
  readonly version: number;
  readonly data: T;
}

function toVersionNumber(value: unknown): number {
  return Number(value) || 0;
}

/**
 * 舊包絡解析邏輯收斂（語義逐字保留自 LprWindow / AiEvidenceWindow /
 * ExportWindow 的 listen 段與 useDesktopWindowSync.unwrapSyncPayload）：
 * 支援 { version, payload } 現行包絡、{ revision, snapshot } 舊包絡、
 * 以及無包絡原始 payload（version 視為 0）。
 */
export function parseTransportEnvelope<T>(payload: unknown): ParsedTransportEnvelope<T> {
  if (payload !== null && typeof payload === 'object') {
    const candidate = payload as Record<string, unknown>;
    if ('version' in candidate && 'payload' in candidate) {
      return { version: toVersionNumber(candidate.version), data: candidate.payload as T };
    }
    if ('revision' in candidate && 'snapshot' in candidate) {
      return { version: toVersionNumber(candidate.revision), data: candidate.snapshot as T };
    }
  }
  return { version: 0, data: payload as T };
}

/**
 * 註冊版本化監聽：包絡解析＋shouldApplyVersion 仲裁（過期版本拒收）。
 * session 通道與 action 通道皆可註冊（action 為無包絡原始 payload，version 恆為 0）。
 * 呼叫端持有回傳的 unlisten 於清理時呼叫。
 */
export async function registerListener<T>(
  channel: ContractChannel<T>,
  handler: (data: T) => void,
  backend: TransportBackend = defaultTransportBackend,
): Promise<() => void> {
  let currentVersion = 0;
  return backend.listen<unknown>(channel.event, (payload) => {
    const envelope = parseTransportEnvelope<T>(payload);
    if (!shouldApplyVersion(currentVersion, envelope.version)) {
      return;
    }
    currentVersion = envelope.version;
    handler(envelope.data);
  });
}

/** main → window：版本化 session 快照（底層 broadcast，單一寫入源為 main window）。 */
export function sendSession<TSession, TAction, TLive>(
  contract: WindowContract<TSession, TAction, TLive>,
  snapshot: TSession,
  version: number,
  backend: TransportBackend = defaultTransportBackend,
): Promise<void> {
  requireDirection(contract.event, 'main-to-window');
  return backend.broadcast(
    contract.windowLabel,
    contract.event.event,
    snapshot,
    version,
  );
}

/** window → main：索取最新 session（payload 恆為 null）。 */
export function requestSession(
  channel: ContractChannel<null>,
  backend: TransportBackend = defaultTransportBackend,
): Promise<void> {
  requireDirection(channel, 'window-to-main');
  return backend.sendToMain(channel.event, null);
}

/** window → main：回傳 action；契約無 action 通道時拋錯。 */
export function sendAction<TSession, TAction, TLive>(
  contract: WindowContract<TSession, TAction, TLive>,
  action: TAction,
  backend: TransportBackend = defaultTransportBackend,
): Promise<void> {
  const channel = contract.actionEvent;
  if (channel === null) {
    throw new TransportContractError(
      `Window "${contract.windowLabel}" contract declares no action channel.`,
    );
  }
  requireDirection(channel, 'window-to-main');
  return backend.sendToMain(channel.event, action);
}

/** main → window：低延遲 live 通道（非版本化底層 send）；契約無 live 通道時拋錯。 */
export function sendLive<TSession, TAction, TLive>(
  contract: WindowContract<TSession, TAction, TLive>,
  payload: TLive,
  backend: TransportBackend = defaultTransportBackend,
): Promise<void> {
  const channel = contract.liveEvent;
  if (channel === null) {
    throw new TransportContractError(
      `Window "${contract.windowLabel}" contract declares no live channel.`,
    );
  }
  requireDirection(channel, 'main-to-window');
  return backend.send(contract.windowLabel, channel.event, payload);
}

export interface WindowErrorInput {
  readonly code: string;
  readonly reason: string;
  readonly sourceWindow: string;
  readonly actionType?: string | null;
}

/** window → main：子視窗 action 失敗回傳 { ok:false, code, reason } 到錯誤通道。 */
export function sendError(
  input: WindowErrorInput,
  backend: TransportBackend = defaultTransportBackend,
): Promise<void> {
  const report = createWindowErrorReport(input);
  return backend.sendToMain(errorReport.event, report);
}

/** main 側：監聽結構化錯誤通道；包絡不符守衛的 payload 直接忽略。 */
export async function registerErrorListener(
  handler: (report: WindowErrorReport) => void,
  backend: TransportBackend = defaultTransportBackend,
): Promise<() => void> {
  return backend.listen<unknown>(errorReport.event, (payload) => {
    if (!isWindowErrorReport(payload)) {
      return;
    }
    handler(payload);
  });
}
