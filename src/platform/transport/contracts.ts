import type {
  AiPanelAction,
  AiPanelSessionSnapshot,
} from '../../modules/editor/application/aiPanelWindow';
import type {
  PlateWindowAction,
  PlateWindowLiveTransport,
  PlateWindowSessionSnapshot,
} from '../../modules/editor/application/plateWindow';
import type {
  ExportProgressPayload,
  ExportSnapshot,
} from '../../modules/export/application/exportTypes';
import type { DesktopWindowId } from '../desktop/windowConfigs';
import type { WindowErrorReport } from './types';

/**
 * Transport 契約表（Blueprint §5.3，Phase 5-A 絞殺起點）。
 *
 * - 事件名字串原樣收錄既有 wire（`editor/*`），wire 不變、零行為變更。
 *   來源：plateWindow.ts / aiPanelWindow.ts / exportWindow.ts 的既有常數，
 *   以及 ExportWindow 監聽的 `editor/export-progress`。
 * - payload 型別直接引用既有模組型別（不複製、不改寫）。
 * - direction 標示該通道的允許流向；runtime 發送端強制檢查。
 * - 遷移期與舊字串常數並存：本表唯讀描述 wire，不觸碰既有傳輸檔；
 *   絞殺順序 plate → ai-panel → export（Wave B/C/D）。
 */
export type TransportDirection = 'main-to-window' | 'window-to-main' | 'both';

export interface ContractChannel<TPayload> {
  readonly event: string;
  readonly direction: TransportDirection;
  readonly payloadType?: TPayload;
}

export interface WindowContract<TSession, TAction, TLive> {
  readonly windowLabel: DesktopWindowId;
  /** session-updated：main → window，版本化快照（VersionedPayload 包絡）。 */
  readonly event: ContractChannel<TSession>;
  /** session-request：window → main，payload 為 null 的索取訊號。 */
  readonly requestEvent: ContractChannel<null>;
  /** action：window → main；該視窗無回傳 action 時為 null（export）。 */
  readonly actionEvent: ContractChannel<TAction> | null;
  /** live：main → window 的低延遲通道；無此通道時為 null。 */
  readonly liveEvent: ContractChannel<TLive> | null;
  readonly direction: TransportDirection;
}

export const plateContract: WindowContract<
  PlateWindowSessionSnapshot,
  PlateWindowAction,
  PlateWindowLiveTransport
> = {
  windowLabel: 'plate',
  event: { event: 'editor/plate-session-updated', direction: 'main-to-window' },
  requestEvent: { event: 'editor/plate-session-request', direction: 'window-to-main' },
  actionEvent: { event: 'editor/plate-action', direction: 'window-to-main' },
  liveEvent: { event: 'editor/plate-live-transport', direction: 'main-to-window' },
  direction: 'both',
};

export const aiPanelContract: WindowContract<AiPanelSessionSnapshot, AiPanelAction, null> = {
  windowLabel: 'ai-panel',
  event: { event: 'editor/ai-panel-session-updated', direction: 'main-to-window' },
  requestEvent: { event: 'editor/ai-panel-session-request', direction: 'window-to-main' },
  actionEvent: { event: 'editor/ai-panel-action', direction: 'window-to-main' },
  liveEvent: null,
  direction: 'both',
};

export const exportContract: WindowContract<ExportSnapshot, null, ExportProgressPayload> = {
  windowLabel: 'export',
  event: { event: 'editor/export-session-updated', direction: 'main-to-window' },
  requestEvent: { event: 'editor/export-session-request', direction: 'window-to-main' },
  actionEvent: null,
  liveEvent: { event: 'editor/export-progress', direction: 'main-to-window' },
  direction: 'both',
};

/**
 * errorReport — 結構化錯誤通道（新事件，既有 wire 無此事件故不與舊字串重疊）。
 * 子視窗 action 失敗 → window-to-main → 主視窗；發送端走 runtime.sendError。
 */
export const errorReport: ContractChannel<WindowErrorReport> = {
  event: 'editor/window-error-report',
  direction: 'window-to-main',
};

export const transportContracts = {
  plate: plateContract,
  aiPanel: aiPanelContract,
  export: exportContract,
};

export type TransportWindowId = keyof typeof transportContracts;
