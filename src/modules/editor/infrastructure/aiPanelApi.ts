import { commands } from '../../../types/bindings';
import { desktopWindowManager } from '../../../platform/desktop';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  AI_PANEL_SESSION_UPDATED_EVENT,
  AI_PANEL_WINDOW_LABEL,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';

export async function openAiPanelWindow() {
  return desktopWindowManager.open(AI_PANEL_WINDOW_LABEL);
}

export function emitAiPanelWindowSession(snapshot: AiPanelSessionSnapshot, revision = 0) {
  return desktopWindowManager.broadcast(AI_PANEL_WINDOW_LABEL, AI_PANEL_SESSION_UPDATED_EVENT, snapshot, revision);
}

export function requestAiPanelWindowSession() {
  return desktopWindowManager.sendToMain(AI_PANEL_SESSION_REQUEST_EVENT, null);
}

export function sendAiPanelAction(action: AiPanelAction) {
  return desktopWindowManager.sendToMain(AI_PANEL_ACTION_EVENT, action);
}

export async function saveGeneratedMediaAsset(sourcePath: string, outputPath: string): Promise<void> {
  const res = await commands.saveGeneratedMediaAsset(sourcePath, outputPath);
  if (res.status === 'ok') return;
  throw new Error(res.error);
}