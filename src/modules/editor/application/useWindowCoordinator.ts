import { useCallback, useEffect, useRef } from 'react';
import type { EditorWorkspaceState, EditorFileState } from '../domain/model';
import { useEditorStore } from './store/store';
import { editorWorkspaceTransport } from './session/editorSessionSync';
import { openPlateWindow, emitPlateWindowSession } from '../infrastructure/plateWindowApi';
import { openAiPanelWindow, emitAiPanelWindowSession } from '../infrastructure/aiPanelApi';
import { openExportWindow, syncExportWindowSession } from '../../export/infrastructure/exportApi';
import { preparePendingExportSession } from '../../export/application/exportSession';
import {
  aiPanelContract,
  exportContract,
  plateContract,
} from '../../../platform/transport/contracts';
import { registerErrorListener, registerListener } from '../../../platform/transport/runtime';
import type {
  AiPanelAction,
  AiPanelSessionSnapshot,
} from './aiPanelWindow';
import type {
  PlateWindowAction,
  PlateWindowSessionSnapshot,
} from './plateWindow';
import type {
  AiEvidenceSessionState,
  LprPlateCandidate,
  LprRuntimeStatus,
  LprSessionState,
  LprTargetAnchor,
} from '../domain/model';
import { createLogger, getErrorSummary, serializeError } from '../../../utils/logger';

const log = createLogger('useWindowCoordinator');

/**
 * Phase 5-D：契約 action 的型別安全分發（取代舊分支表）。
 * handler 表以 action type 為鍵、逐項承接原分發語義；
 * 執行期未知 type 沿用原 default 行為直接忽略。
 */
async function dispatchContractAction<Action extends { readonly type: string }>(
  action: Action,
  handlers: {
    [Key in Action['type']]: (action: Extract<Action, { type: Key }>) => Promise<void> | void;
  },
): Promise<void> {
  // 相關聯合（correlated union）分發：handler 表以 type 為鍵完備覆蓋；
  // 未知 type 沿用原 default 語義忽略。經 unknown 中轉為 TS 已知限制下的寫法。
  const table = handlers as unknown as Record<string, ((action: Action) => Promise<void> | void) | undefined>;
  const handler = table[action.type];
  if (handler === undefined) {
    return;
  }
  await handler(action);
}

export interface UseWindowCoordinatorOptions {
  state: EditorWorkspaceState;
  sessionRevision: number;
  activeFile: EditorFileState | null | undefined;
  currentPlayheadMs: number;
  currentIsPlaying: boolean;

  // From LPR Workflow
  lprRuntimeStatus: LprRuntimeStatus | null;
  lprState: LprSessionState;
  lprTopCandidate: LprPlateCandidate | null;
  lprSelectedTargetAnchor: LprTargetAnchor | null;
  canAnalyzeRange: boolean;
  latestCountryHintDraftRef: React.MutableRefObject<string | null>;
  refreshLprRuntimeStatus: () => Promise<void>;
  handleCancelLprJob: () => Promise<void>;
  handleUseClipInterval: () => void;
  handleSetIntervalBoundary: (boundary: 'start' | 'end') => void;
  applyCountryHints: (draft: string) => string[];
  handleScanLprTargets: () => Promise<void>;
  handleAnalyzeLprFrame: () => Promise<void>;
  handleAnalyzeLprInterval: () => Promise<void>;
  handleExportLprEvidence: () => Promise<void>;
  handleSelectTargetTrack: (targetTrackId: string, preferredTimeMs?: number | null) => void;

  // From AI Evidence Workflow
  aiState: AiEvidenceSessionState;
  handleRunAiEvidence: (prompt: string) => Promise<void>;
  handleCancelAiJob: () => Promise<void>;

  setWorkspaceFeedback: (message: string | null) => void;
  plateWindowLiveSyncEnabledRef?: React.MutableRefObject<boolean>;
}

export function useWindowCoordinator({
  state,
  sessionRevision,
  activeFile,
  currentPlayheadMs,
  currentIsPlaying,
  lprRuntimeStatus,
  lprState,
  lprTopCandidate,
  lprSelectedTargetAnchor,
  canAnalyzeRange,
  latestCountryHintDraftRef,
  refreshLprRuntimeStatus,
  handleCancelLprJob,
  handleUseClipInterval,
  handleSetIntervalBoundary,
  applyCountryHints,
  handleScanLprTargets,
  handleAnalyzeLprFrame,
  handleAnalyzeLprInterval,
  handleExportLprEvidence,
  handleSelectTargetTrack,
  aiState,
  handleRunAiEvidence,
  handleCancelAiJob,
  setWorkspaceFeedback,
  plateWindowLiveSyncEnabledRef: externalLiveSyncRef,
}: UseWindowCoordinatorOptions) {
  const internalLiveSyncRef = useRef(false);
  const plateWindowLiveSyncEnabledRef = externalLiveSyncRef ?? internalLiveSyncRef;

  const buildPlateWindowSnapshot = useCallback((): PlateWindowSessionSnapshot => ({
    workspaceName: state.workspaceName,
    activeFileName: activeFile?.asset.name ?? null,
    hasActiveFile: Boolean(activeFile),
    runtimeStatus: lprRuntimeStatus,
    lpr: lprState,
    explicitInterval: lprState.interval,
    effectiveInterval: lprState.interval,
    canAnalyzeRange,
    topCandidate: lprTopCandidate,
    anchorTimeMs: Math.max(0, Math.round(lprSelectedTargetAnchor?.timeMs ?? currentPlayheadMs)),
    playheadMs: Math.max(0, Math.round(currentPlayheadMs)),
  }), [activeFile, canAnalyzeRange, currentPlayheadMs, lprRuntimeStatus, lprSelectedTargetAnchor, lprState, lprTopCandidate, state.workspaceName]);

  const buildAiPanelWindowSnapshot = useCallback((): AiPanelSessionSnapshot => ({
    workspaceName: state.workspaceName,
    activeFileName: activeFile?.asset.name ?? null,
    hasActiveFile: Boolean(activeFile),
    runtimeStatus: lprRuntimeStatus,
    lpr: lprState,
    ai: aiState,
    playheadMs: Math.max(0, Math.round(currentPlayheadMs)),
  }), [activeFile, aiState, currentPlayheadMs, lprRuntimeStatus, lprState, state.workspaceName]);

  const handleOpenPlateWindow = useCallback(async () => {
    await openPlateWindow();
    plateWindowLiveSyncEnabledRef.current = true;
    await emitPlateWindowSession(buildPlateWindowSnapshot(), sessionRevision).catch(() => undefined);
  }, [buildPlateWindowSnapshot, plateWindowLiveSyncEnabledRef, sessionRevision]);

  const handleOpenAiPanelWindow = useCallback(async () => {
    await openAiPanelWindow();
    await emitAiPanelWindowSession(buildAiPanelWindowSnapshot(), sessionRevision).catch(() => undefined);
  }, [buildAiPanelWindowSnapshot, sessionRevision]);

  const handleOpenExportWindow = useCallback(async () => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    try {
      const snapshot = preparePendingExportSession(state);
      await openExportWindow(snapshot, sessionRevision);
    } catch (error) {
      log.error('Failed to open export window.', {
        error: serializeError(error),
        fileCount: state.files.length,
      });
      setWorkspaceFeedback(getErrorSummary(error, 'Failed to open export window.'));
    }
  }, [activeFile, sessionRevision, setWorkspaceFeedback, state]);

  const handleToggleCompactExports = useCallback(() => {
    if (!activeFile) {
      return;
    }

    const compressionMode = activeFile.renderProfile.compressionMode === 'compact' ? 'standard' : 'compact';
    editorWorkspaceTransport.setRenderProfile({ compressionMode });

    try {
      const snapshot = preparePendingExportSession(state);
      snapshot.renderProfile = {
        ...snapshot.renderProfile,
        compressionMode,
      };
      void syncExportWindowSession(snapshot, sessionRevision);
    } catch {
      // Ignore export-session sync failures when no exportable timeline is available.
    }
  }, [activeFile, sessionRevision, state]);

  // Keep actions in a ref to avoid re-subscribing event listeners on every change
  const actionsRef = useRef({
    refreshLprRuntimeStatus,
    handleCancelLprJob,
    handleUseClipInterval,
    handleSetIntervalBoundary,
    applyCountryHints,
    handleScanLprTargets,
    handleAnalyzeLprFrame,
    handleAnalyzeLprInterval,
    handleExportLprEvidence,
    handleSelectTargetTrack,
    handleRunAiEvidence,
    handleCancelAiJob,
    setWorkspaceFeedback,
    buildPlateWindowSnapshot,
    buildAiPanelWindowSnapshot,
    state,
    sessionRevision,
    activeFile,
    currentIsPlaying,
    lprState,
  });

  useEffect(() => {
    actionsRef.current = {
      refreshLprRuntimeStatus,
      handleCancelLprJob,
      handleUseClipInterval,
      handleSetIntervalBoundary,
      applyCountryHints,
      handleScanLprTargets,
      handleAnalyzeLprFrame,
      handleAnalyzeLprInterval,
      handleExportLprEvidence,
      handleSelectTargetTrack,
      handleRunAiEvidence,
      handleCancelAiJob,
      setWorkspaceFeedback,
      buildPlateWindowSnapshot,
      buildAiPanelWindowSnapshot,
      state,
      sessionRevision,
      activeFile,
      currentIsPlaying,
      lprState,
    };
  });

  // Phase 5-D：聲明式 contract glue —— 註冊 contract list（plate / ai-panel /
  // export 三契約＋errorReport），action 分發走 typed handler map（原分發
  // 逐項搬遷、語義一字不差）；session 同步發送走各視窗 emit（經
  // runtime.sendSession）；open 系仍走 DesktopWindowManager（經各視窗 open*
  // 函式）。本 effect 內無舊分支表、手寫包絡解析、直接傳輸調用。
  useEffect(() => {
    let disposed = false;
    const cleanups: Array<() => void> = [];
    const trackRegistration = (registration: Promise<() => void>): void => {
      void registration.then((unlisten) => {
        cleanups.push(unlisten);
      });
    };

    const reportActionFailure = (sourceWindow: string, error: unknown): void => {
      log.error(`Failed to handle ${sourceWindow} window action.`, {
        error: serializeError(error),
      });
      actionsRef.current.setWorkspaceFeedback(
        getErrorSummary(error, `Failed to handle ${sourceWindow} window action.`),
      );
    };

    const plateActionHandlers: {
      [Key in PlateWindowAction['type']]: (
        action: Extract<PlateWindowAction, { type: Key }>,
      ) => Promise<void> | void;
    } = {
      'refresh-runtime': async () => {
        await actionsRef.current.refreshLprRuntimeStatus();
      },
      'cancel-job': async () => {
        await actionsRef.current.handleCancelLprJob();
      },
      'use-clip-interval': () => {
        actionsRef.current.handleUseClipInterval();
      },
      'set-interval-boundary': (action) => {
        actionsRef.current.handleSetIntervalBoundary(action.boundary);
      },
      'clear-interval': () => {
        useEditorStore.getState().clearLprInterval();
      },
      'set-analysis-profile': (action) => {
        useEditorStore.getState().setLprAnalysisProfile(action.analysisProfileId);
      },
      'set-country-hints': (action) => {
        latestCountryHintDraftRef.current = action.value;
        actionsRef.current.applyCountryHints(action.value);
      },
      'scan-targets': async () => {
        await actionsRef.current.handleScanLprTargets();
      },
      'analyze-frame': async () => {
        await actionsRef.current.handleAnalyzeLprFrame();
      },
      'analyze-range': async () => {
        await actionsRef.current.handleAnalyzeLprInterval();
      },
      'toggle-dense-sampling': () => {
        useEditorStore.getState().setLprToggles({ useDenseSampling: !actionsRef.current.lprState.useDenseSampling });
      },
      'toggle-developer-diagnostics': () => {
        useEditorStore.getState().setLprToggles({ showDeveloperDiagnostics: !actionsRef.current.lprState.showDeveloperDiagnostics });
      },
      'export-evidence': async () => {
        await actionsRef.current.handleExportLprEvidence();
      },
      'clear-results': () => {
        useEditorStore.getState().clearLprResults();
      },
      'select-target-track': (action) => {
        actionsRef.current.handleSelectTargetTrack(action.targetTrackId, action.anchorTimeMs);
      },
      'accept-candidate': (action) => {
        useEditorStore.getState().acceptLprCandidate(action.candidateId);
      },
      'seek-to-sample': (action) => {
        useEditorStore.getState().setPlayhead(Math.max(0, Math.round(action.timeMs)));
        if (actionsRef.current.currentIsPlaying) {
          useEditorStore.getState().setPlaying(false);
        }
      },
    };

    const aiPanelActionHandlers: {
      [Key in AiPanelAction['type']]: (
        action: Extract<AiPanelAction, { type: Key }>,
      ) => Promise<void> | void;
    } = {
      'run-analysis': async (action) => {
        await actionsRef.current.handleRunAiEvidence(action.prompt);
      },
      'cancel-job': async () => {
        await actionsRef.current.handleCancelAiJob();
      },
      'seek-to-time': (action) => {
        useEditorStore.getState().setPlayhead(Math.max(0, Math.round(action.timeMs)));
        if (actionsRef.current.currentIsPlaying) {
          useEditorStore.getState().setPlaying(false);
        }
      },
      'reset-session': () => {
        if (actionsRef.current.activeFile) {
          useEditorStore.getState().resetAiSession(actionsRef.current.activeFile.id);
        }
      },
    };

    // action 通道：僅具 actionEvent 的契約註冊（export 無 action 通道，契約驅動略過）。
    if (plateContract.actionEvent !== null) {
      const plateActionChannel = plateContract.actionEvent;
      trackRegistration(registerListener(plateActionChannel, (action: PlateWindowAction) => {
        if (disposed) {
          return;
        }
        void dispatchContractAction(action, plateActionHandlers).catch((error: unknown) => {
          reportActionFailure('plate', error);
        });
      }));
    }

    if (aiPanelContract.actionEvent !== null) {
      const aiPanelActionChannel = aiPanelContract.actionEvent;
      trackRegistration(registerListener(aiPanelActionChannel, (action: AiPanelAction) => {
        if (disposed) {
          return;
        }
        void dispatchContractAction(action, aiPanelActionHandlers).catch((error: unknown) => {
          reportActionFailure('ai-panel', error);
        });
      }));
    }

    // session-request 三通道：契約 requestEvent 註冊（原三 listen 合併）。
    trackRegistration(registerListener(plateContract.requestEvent, () => {
      if (disposed) {
        return;
      }
      plateWindowLiveSyncEnabledRef.current = true;
      const actions = actionsRef.current;
      void emitPlateWindowSession(actions.buildPlateWindowSnapshot(), actions.sessionRevision).catch(() => undefined);
    }));

    trackRegistration(registerListener(aiPanelContract.requestEvent, () => {
      if (disposed) {
        return;
      }
      const actions = actionsRef.current;
      void emitAiPanelWindowSession(actions.buildAiPanelWindowSnapshot(), actions.sessionRevision).catch(() => undefined);
    }));

    trackRegistration(registerListener(exportContract.requestEvent, () => {
      if (disposed) {
        return;
      }
      const actions = actionsRef.current;
      try {
        const snapshot = preparePendingExportSession(actions.state);
        void syncExportWindowSession(snapshot, actions.sessionRevision).catch(() => undefined);
      } catch {
        // Ignore export-session requests when no exportable timeline is available.
      }
    }));

    // 結構化錯誤通道：主視窗可達，落 workspace feedback。
    trackRegistration(registerErrorListener((report) => {
      if (disposed) {
        return;
      }
      actionsRef.current.setWorkspaceFeedback(report.reason);
    }));

    return () => {
      disposed = true;
      for (const unlisten of cleanups) {
        unlisten();
      }
    };
  }, [latestCountryHintDraftRef, plateWindowLiveSyncEnabledRef]);

  // Periodic/Snapshot update synchronization
  useEffect(() => {
    void emitPlateWindowSession(buildPlateWindowSnapshot(), sessionRevision).catch(() => undefined);
  }, [buildPlateWindowSnapshot, sessionRevision]);

  useEffect(() => {
    void emitAiPanelWindowSession(buildAiPanelWindowSnapshot(), sessionRevision).catch(() => undefined);
  }, [buildAiPanelWindowSnapshot, sessionRevision]);

  return {
    plateWindowLiveSyncEnabledRef,
    buildPlateWindowSnapshot,
    buildAiPanelWindowSnapshot,
    handleOpenPlateWindow,
    handleOpenAiPanelWindow,
    handleOpenExportWindow,
    handleToggleCompactExports,
  };
}
