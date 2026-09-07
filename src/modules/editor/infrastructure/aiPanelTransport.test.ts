import { describe, expect, it } from 'vitest';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  AI_PANEL_SESSION_UPDATED_EVENT,
  AI_PANEL_WINDOW_LABEL,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';
import { buildDefaultAiEvidenceState } from '../domain/aiEvidenceState';
import { buildDefaultLprState } from '../domain/lprState';
import { aiPanelContract } from '../../../platform/transport/contracts';
import { isWorkspaceRuntimeSnapshot } from '../../../platform/transport/types';

/**
 * Phase 5-C 絞殺門檻：ai-panel 走 aiPanelContract、wire 不變、快照收斂。
 * 不觸碰 transport 核心四檔，僅從呼叫端斷言契約。
 */
describe('ai-panel transport contract — Phase 5-C 絞殺', () => {
  it('契約沿用既有字串且無 live 通道', () => {
    expect(aiPanelContract.windowLabel).toBe(AI_PANEL_WINDOW_LABEL);
    expect(aiPanelContract.event.event).toBe(AI_PANEL_SESSION_UPDATED_EVENT);
    expect(aiPanelContract.requestEvent.event).toBe(AI_PANEL_SESSION_REQUEST_EVENT);
    expect(aiPanelContract.actionEvent?.event).toBe(AI_PANEL_ACTION_EVENT);
    expect(aiPanelContract.liveEvent).toBeNull();
  });

  it('快照收斂到 WorkspaceRuntimeSnapshot＋ai-panel 自身欄位', () => {
    const snapshot: AiPanelSessionSnapshot = {
      workspaceName: 'workspace',
      activeFileName: 'clip.mp4',
      hasActiveFile: true,
      runtimeStatus: null,
      playheadMs: 0,
      liveTransport: null,
      lpr: buildDefaultLprState(),
      ai: buildDefaultAiEvidenceState(),
    };
    expect(isWorkspaceRuntimeSnapshot(snapshot)).toBe(true);
    expect(snapshot.lpr).toBeDefined();
    expect(snapshot.ai).toBeDefined();
  });
});
