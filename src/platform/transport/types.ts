import type { LiveTransportSnapshot } from '../../modules/editor/application/liveTransport';
import type { LprRuntimeStatus } from '../../modules/editor/domain/model';

/**
 * WorkspaceRuntimeSnapshot — Phase 5 transport 共用快照基底（Blueprint §5.3）。
 *
 * 收斂各視窗近重複 snapshot 型別：runtimeStatus＋playheadMs＋transport 層級
 * （liveTransport）為共用欄位，各視窗僅在其自身快照型別上加欄位。
 * 單一寫入源維持 main window；version 仲裁語義不變（見 runtime.ts）。
 * 本單元僅新增共用型別，既有視窗快照型別零改動（絞殺前提）。
 */
export interface WorkspaceRuntimeSnapshot {
  readonly workspaceName: string;
  readonly activeFileName: string | null;
  readonly hasActiveFile: boolean;
  readonly runtimeStatus: LprRuntimeStatus | null;
  readonly playheadMs: number;
  readonly liveTransport: LiveTransportSnapshot | null;
}

export function isWorkspaceRuntimeSnapshot(value: unknown): value is WorkspaceRuntimeSnapshot {
  if (value === null || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.workspaceName === 'string' &&
    (typeof candidate.activeFileName === 'string' || candidate.activeFileName === null) &&
    typeof candidate.hasActiveFile === 'boolean' &&
    (candidate.runtimeStatus === null || typeof candidate.runtimeStatus === 'object') &&
    typeof candidate.playheadMs === 'number' &&
    (candidate.liveTransport === null || typeof candidate.liveTransport === 'object')
  );
}

/**
 * WindowErrorReport — 結構化錯誤通道 payload（Blueprint §5.3「結構化錯誤事件」）。
 *
 * 子視窗 action 失敗時回傳給主視窗：{ ok:false, code, reason }＋來源視窗＋觸發 action。
 * 以 `ok: false` 字面量與成功載荷區分；wire 事件名見 contracts.errorReport。
 */
export interface WindowErrorReport {
  readonly ok: false;
  readonly code: string;
  readonly reason: string;
  readonly sourceWindow: string;
  readonly actionType: string | null;
}

export function createWindowErrorReport(input: {
  readonly code: string;
  readonly reason: string;
  readonly sourceWindow: string;
  readonly actionType?: string | null;
}): WindowErrorReport {
  return {
    ok: false,
    code: input.code,
    reason: input.reason,
    sourceWindow: input.sourceWindow,
    actionType: input.actionType ?? null,
  };
}

export function isWindowErrorReport(value: unknown): value is WindowErrorReport {
  if (value === null || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    candidate.ok === false &&
    typeof candidate.code === 'string' &&
    typeof candidate.reason === 'string' &&
    typeof candidate.sourceWindow === 'string' &&
    (typeof candidate.actionType === 'string' || candidate.actionType === null)
  );
}
