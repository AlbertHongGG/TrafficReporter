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
import { createRevisionedWindowSnapshot } from '../../../vnext/windowing/revisionedSnapshot';

function waitForWindowCreation(plateWindow: WebviewWindow) {
  return new Promise<WebviewWindow>((resolve, reject) => {
    let settled = false;
    let createdCleanup: (() => void) | undefined;
    let errorCleanup: (() => void) | undefined;
    const timeoutId = window.setTimeout(() => {
      settleReject(new Error('Timed out while creating the plate window.'));
    }, 4000);

    const cleanup = () => {
      window.clearTimeout(timeoutId);
      createdCleanup?.();
      errorCleanup?.();
    };

    const settleResolve = () => {
      if (settled) {
        return;
      }

      settled = true;
      cleanup();
      resolve(plateWindow);
    };

    const settleReject = (error: unknown) => {
      if (settled) {
        return;
      }

      settled = true;
      cleanup();
      reject(error instanceof Error ? error : new Error('Failed to create the plate window.'));
    };

    void plateWindow.once('tauri://created', () => {
      settleResolve();
    }).then((unlisten) => {
      createdCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });

    void plateWindow.once<string>('tauri://error', (event) => {
      settleReject(new Error(typeof event.payload === 'string' ? event.payload : 'Failed to create the plate window.'));
    }).then((unlisten) => {
      errorCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });
  });
}

export async function openPlateWindow() {
  const existingWindow = await WebviewWindow.getByLabel(PLATE_WINDOW_LABEL);
  if (existingWindow) {
    await existingWindow.show().catch(() => undefined);
    await existingWindow.setFocus().catch(() => undefined);
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
