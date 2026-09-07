import { desktopWindowManager } from '../../../platform/desktop';
import { plateContract } from '../../../platform/transport/contracts';
import {
  requestSession,
  sendAction,
  sendLive,
  sendSession,
  type TransportBackend,
} from '../../../platform/transport/runtime';
import {
  PLATE_WINDOW_LABEL,
  type PlateWindowLiveTransport,
  type PlateWindowAction,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';

export async function openPlateWindow() {
  return desktopWindowManager.open(PLATE_WINDOW_LABEL);
}

/**
 * 主視窗 → plate：版本化 session 快照（單一寫入源為 main window）。
 * 走 transport runtime（plateContract.event），wire 事件名字串不變。
 */
export function emitPlateWindowSession(
  snapshot: PlateWindowSessionSnapshot,
  revision = 0,
  backend?: TransportBackend,
) {
  return sendSession(plateContract, snapshot, revision, backend);
}

/**
 * 主視窗 → plate：低延遲 live 傳輸（非版本化）。
 * 走 transport runtime（plateContract.liveEvent），wire 事件名字串不變。
 */
export function emitPlateWindowLiveTransport(
  transport: PlateWindowLiveTransport,
  backend?: TransportBackend,
) {
  return sendLive(plateContract, transport, backend);
}

/**
 * plate → 主視窗：索取最新 session（payload 恆為 null，只讀＋request，不寫 snapshot）。
 * 走 transport runtime（plateContract.requestEvent），wire 事件名字串不變。
 */
export function requestPlateWindowSession(backend?: TransportBackend) {
  return requestSession(plateContract.requestEvent, backend);
}

/**
 * plate → 主視窗：回傳 action。
 * 走 transport runtime（plateContract.actionEvent），wire 事件名字串不變。
 */
export function sendPlateWindowAction(action: PlateWindowAction, backend?: TransportBackend) {
  return sendAction(plateContract, action, backend);
}
