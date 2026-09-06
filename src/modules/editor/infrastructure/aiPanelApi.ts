import { commands } from '../../../types/bindings';
import { emitTo } from '@tauri-apps/api/event';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  AI_PANEL_SESSION_UPDATED_EVENT,
  AI_PANEL_WINDOW_LABEL,
  AI_PANEL_WINDOW_URL,
  MAIN_WINDOW_LABEL,
  type RevisionedAiPanelSessionSnapshot,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';
import {
  createRevisionedWindowSnapshot,
  focusExistingWindow,
  waitForWindowCreation,
} from '../../../app/windowing';

export async function openAiPanelWindow() {
  const existingWindow = await focusExistingWindow(AI_PANEL_WINDOW_LABEL);
  if (existingWindow) {
    return existingWindow;
  }

  const aiPanelWindow = new WebviewWindow(AI_PANEL_WINDOW_LABEL, {
    url: AI_PANEL_WINDOW_URL,
    title: 'AI Evidence',
    width: 980,
    height: 760,
    minWidth: 720,
    minHeight: 560,
    resizable: true,
    focus: true,
    center: true,
    decorations: false,
    transparent: false,
  });

  return waitForWindowCreation(aiPanelWindow);
}

export function emitAiPanelWindowSession(snapshot: AiPanelSessionSnapshot, revision = 0) {
  const payload: RevisionedAiPanelSessionSnapshot = createRevisionedWindowSnapshot(snapshot, revision);
  return emitTo(AI_PANEL_WINDOW_LABEL, AI_PANEL_SESSION_UPDATED_EVENT, payload);
}

export function requestAiPanelWindowSession() {
  return emitTo(MAIN_WINDOW_LABEL, AI_PANEL_SESSION_REQUEST_EVENT);
}

export function sendAiPanelAction(action: AiPanelAction) {
  return emitTo(MAIN_WINDOW_LABEL, AI_PANEL_ACTION_EVENT, action);
}

export async function saveGeneratedMediaAsset(sourcePath: string, outputPath: string): Promise<void> {
  const res = await commands.saveGeneratedMediaAsset(sourcePath, outputPath);
  if (res.status === 'ok') return;
  throw new Error(res.error);
}