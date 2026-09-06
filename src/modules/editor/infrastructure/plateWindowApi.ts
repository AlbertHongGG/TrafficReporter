import { emitTo } from '@tauri-apps/api/event';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
import {
  MAIN_WINDOW_LABEL,
  PLATE_ACTION_EVENT,
  PLATE_LIVE_TRANSPORT_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  PLATE_SESSION_UPDATED_EVENT,
  PLATE_WINDOW_LABEL,
  PLATE_WINDOW_URL,
  type PlateWindowLiveTransport,
  type RevisionedPlateWindowSessionSnapshot,
  type PlateWindowAction,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';
import {
  createRevisionedWindowSnapshot,
  focusExistingWindow,
  waitForWindowCreation,
} from '../../../app/windowing';

export async function openPlateWindow() {
  const existingWindow = await focusExistingWindow(PLATE_WINDOW_LABEL);
  if (existingWindow) {
    return existingWindow;
  }

  const plateWindow = new WebviewWindow(PLATE_WINDOW_LABEL, {
    url: PLATE_WINDOW_URL,
    title: 'Plate',
    width: 720,
    height: 860,
    minWidth: 720,
    minHeight: 560,
    resizable: true,
    focus: true,
    center: true,
    decorations: false,
    transparent: false,
  });

  return waitForWindowCreation(plateWindow);
}

export function emitPlateWindowSession(snapshot: PlateWindowSessionSnapshot, revision = 0) {
  const payload: RevisionedPlateWindowSessionSnapshot = createRevisionedWindowSnapshot(snapshot, revision);
  return emitTo(PLATE_WINDOW_LABEL, PLATE_SESSION_UPDATED_EVENT, payload);
}

export function emitPlateWindowLiveTransport(transport: PlateWindowLiveTransport) {
  return emitTo(PLATE_WINDOW_LABEL, PLATE_LIVE_TRANSPORT_EVENT, transport);
}

export function requestPlateWindowSession() {
  return emitTo(MAIN_WINDOW_LABEL, PLATE_SESSION_REQUEST_EVENT);
}

export function sendPlateWindowAction(action: PlateWindowAction) {
  return emitTo(MAIN_WINDOW_LABEL, PLATE_ACTION_EVENT, action);
}
