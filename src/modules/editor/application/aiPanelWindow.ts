import type { AiEvidenceSessionState, LprRuntimeStatus, LprSessionState } from '../domain/model';
import type { VersionedPayload } from '../../../platform/desktop';

export const MAIN_WINDOW_LABEL = 'main';
export const AI_PANEL_WINDOW_LABEL = 'ai-panel';
export const AI_PANEL_WINDOW_URL = 'index.html?window=ai-panel';
export const AI_PANEL_SESSION_UPDATED_EVENT = 'editor/ai-panel-session-updated';
export const AI_PANEL_SESSION_REQUEST_EVENT = 'editor/ai-panel-session-request';
export const AI_PANEL_ACTION_EVENT = 'editor/ai-panel-action';

export interface AiPanelSessionSnapshot {
  workspaceName: string;
  activeFileName: string | null;
  hasActiveFile: boolean;
  runtimeStatus: LprRuntimeStatus | null;
  lpr: LprSessionState;
  ai: AiEvidenceSessionState;
  playheadMs: number;
}

export type RevisionedAiPanelSessionSnapshot = VersionedPayload<AiPanelSessionSnapshot>;

export type AiPanelAction =
  | { type: 'run-analysis'; prompt: string }
  | { type: 'cancel-job' }
  | { type: 'seek-to-time'; timeMs: number }
  | { type: 'reset-session' };