import { emitTo } from '@tauri-apps/api/event';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  AI_PANEL_SESSION_UPDATED_EVENT,
  AI_PANEL_WINDOW_LABEL,
  AI_PANEL_WINDOW_URL,
  MAIN_WINDOW_LABEL,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';

function waitForWindowCreation(aiPanelWindow: WebviewWindow) {
  return new Promise<WebviewWindow>((resolve, reject) => {
    let settled = false;
    let createdCleanup: (() => void) | undefined;
    let errorCleanup: (() => void) | undefined;
    const timeoutId = window.setTimeout(() => {
      settleReject(new Error('Timed out while creating the AI panel window.'));
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
      resolve(aiPanelWindow);
    };

    const settleReject = (error: unknown) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(error instanceof Error ? error : new Error('Failed to create the AI panel window.'));
    };

    void aiPanelWindow.once('tauri://created', () => {
      settleResolve();
    }).then((unlisten) => {
      createdCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });

    void aiPanelWindow.once<string>('tauri://error', (event) => {
      settleReject(new Error(typeof event.payload === 'string' ? event.payload : 'Failed to create the AI panel window.'));
    }).then((unlisten) => {
      errorCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });
  });
}

export async function openAiPanelWindow() {
  const existingWindow = await WebviewWindow.getByLabel(AI_PANEL_WINDOW_LABEL);
  if (existingWindow) {
    await existingWindow.show().catch(() => undefined);
    await existingWindow.setFocus().catch(() => undefined);
    return existingWindow;
  }

  const aiPanelWindow = new WebviewWindow(AI_PANEL_WINDOW_LABEL, {
    url: AI_PANEL_WINDOW_URL,
    title: 'AI Evidence',
    width: 920,
    height: 860,
    minWidth: 760,
    minHeight: 620,
    resizable: true,
    focus: true,
    center: true,
    decorations: false,
    transparent: false,
  });

  return waitForWindowCreation(aiPanelWindow);
}

export function emitAiPanelWindowSession(snapshot: AiPanelSessionSnapshot) {
  return emitTo(AI_PANEL_WINDOW_LABEL, AI_PANEL_SESSION_UPDATED_EVENT, snapshot);
}

export function requestAiPanelWindowSession() {
  return emitTo(MAIN_WINDOW_LABEL, AI_PANEL_SESSION_REQUEST_EVENT);
}

export function sendAiPanelAction(action: AiPanelAction) {
  return emitTo(MAIN_WINDOW_LABEL, AI_PANEL_ACTION_EVENT, action);
}