import { commands } from '../../../types/bindings';
import { unwrapCommand } from '../../../infrastructure/ipc-unwrap';
import { parseSaveGeneratedMediaAssetResponse } from './mediaSchemas';
import { desktopWindowManager } from '../../../platform/desktop';
import { aiPanelContract } from '../../../platform/transport/contracts';
import { requestSession, sendAction, sendSession } from '../../../platform/transport/runtime';
import {
  AI_PANEL_WINDOW_LABEL,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';

export async function openAiPanelWindow() {
  return desktopWindowManager.open(AI_PANEL_WINDOW_LABEL);
}

/**
 * Phase 5-C 絞殺：ai-panel 單一寫入源維持 main window，本函式為唯一 session
 * 發送入口（經 transport runtime.sendSession 走 aiPanelContract 通道；wire
 * 事件名字串不變）。舊 desktopWindowManager.broadcast 直寫已移除，無雙寫。
 */
export function emitAiPanelWindowSession(snapshot: AiPanelSessionSnapshot, revision = 0) {
  return sendSession(aiPanelContract, snapshot, revision);
}

/** window → main 索取最新 session（經 runtime.requestSession；payload 恆為 null）。 */
export function requestAiPanelWindowSession() {
  return requestSession(aiPanelContract.requestEvent);
}

/** window → main 回傳 action（經 runtime.sendAction 走 aiPanelContract 通道）。 */
export function sendAiPanelAction(action: AiPanelAction) {
  return sendAction(aiPanelContract, action);
}

export async function saveGeneratedMediaAsset(sourcePath: string, outputPath: string): Promise<void> {
  const raw = await unwrapCommand(
    commands.saveGeneratedMediaAsset(sourcePath, outputPath),
    'save_generated_media_asset',
  );
  parseSaveGeneratedMediaAssetResponse('save_generated_media_asset', raw);
}