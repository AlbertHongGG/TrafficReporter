import { commands } from '../../../types/bindings';
import { unwrapCommand } from '../../../infrastructure/ipc-unwrap';
import { parseSaveGeneratedMediaAssetResponse } from './mediaSchemas';
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
  const raw = await unwrapCommand(
    commands.saveGeneratedMediaAsset(sourcePath, outputPath),
    'save_generated_media_asset',
  );
  parseSaveGeneratedMediaAssetResponse('save_generated_media_asset', raw);
}