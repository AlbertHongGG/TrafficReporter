import type { AiEvidenceSessionState, LprSessionState } from '../domain/model';
import type { VersionedPayload } from '../../../platform/desktop';
import type { WorkspaceRuntimeSnapshot } from '../../../platform/transport/types';
import type { LiveTransportSnapshot } from './liveTransport';

export const MAIN_WINDOW_LABEL = 'main';
export const AI_PANEL_WINDOW_LABEL = 'ai-panel';
export const AI_PANEL_WINDOW_URL = 'index.html?window=ai-panel';
export const AI_PANEL_SESSION_UPDATED_EVENT = 'editor/ai-panel-session-updated';
export const AI_PANEL_SESSION_REQUEST_EVENT = 'editor/ai-panel-session-request';
export const AI_PANEL_ACTION_EVENT = 'editor/ai-panel-action';

/**
 * Phase 5-C 絞殺：快照型別收斂到 WorkspaceRuntimeSnapshot 交叉 ai-panel 自身欄位。
 * 共用欄位（workspaceName / activeFileName / hasActiveFile / runtimeStatus /
 * playheadMs）由基底提供；lpr / ai 為 ai-panel 自身欄位。
 * aiPanelContract.liveEvent 為 null（無 live 通道），故 liveTransport 收斂為
 * 可選（缺席視為無 live 傳輸）；coordinator 既有字面量零改動仍可賦值。
 */
export type AiPanelSessionSnapshot = Omit<WorkspaceRuntimeSnapshot, 'liveTransport'> & {
  liveTransport?: LiveTransportSnapshot | null;
  lpr: LprSessionState;
  ai: AiEvidenceSessionState;
};

export type RevisionedAiPanelSessionSnapshot = VersionedPayload<AiPanelSessionSnapshot>;

export type AiPanelAction =
  | { type: 'run-analysis'; prompt: string }
  | { type: 'cancel-job' }
  | { type: 'seek-to-time'; timeMs: number }
  | { type: 'reset-session' };