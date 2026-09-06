import { desktopWindowManager } from '../../../platform/desktop';
import {
  PLATE_ACTION_EVENT,
  PLATE_LIVE_TRANSPORT_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  PLATE_SESSION_UPDATED_EVENT,
  PLATE_WINDOW_LABEL,
  type PlateWindowLiveTransport,
  type PlateWindowAction,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';

export async function openPlateWindow() {
  return desktopWindowManager.open(PLATE_WINDOW_LABEL);
}

export function emitPlateWindowSession(snapshot: PlateWindowSessionSnapshot, revision = 0) {
  return desktopWindowManager.broadcast(PLATE_WINDOW_LABEL, PLATE_SESSION_UPDATED_EVENT, snapshot, revision);
}

export function emitPlateWindowLiveTransport(transport: PlateWindowLiveTransport) {
  return desktopWindowManager.send(PLATE_WINDOW_LABEL, PLATE_LIVE_TRANSPORT_EVENT, transport);
}

export function requestPlateWindowSession() {
  return desktopWindowManager.sendToMain(PLATE_SESSION_REQUEST_EVENT, null);
}

export function sendPlateWindowAction(action: PlateWindowAction) {
  return desktopWindowManager.sendToMain(PLATE_ACTION_EVENT, action);
}
