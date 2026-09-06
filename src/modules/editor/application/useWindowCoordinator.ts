import { useCallback, useEffect, useRef } from 'react';
import { listen } from '@tauri-apps/api/event';
import type { EditorWorkspaceState, EditorFileState } from '../domain/model';
import type { EditorAction } from './editorReducer';
import { openPlateWindow, emitPlateWindowSession } from '../infrastructure/plateWindowApi';
import { openAiPanelWindow, emitAiPanelWindowSession } from '../infrastructure/aiPanelApi';
import { openExportWindow, syncExportWindowSession } from '../../export/infrastructure/exportApi';
import { preparePendingExportSession } from '../../export/application/exportSession';
import { EXPORT_SESSION_REQUEST_EVENT } from '../../export/application/exportWindow';
import {
  AI_PANEL_ACTION_EVENT,
  AI_PANEL_SESSION_REQUEST_EVENT,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from './aiPanelWindow';
import {
  PLATE_ACTION_EVENT,
  PLATE_SESSION_REQUEST_EVENT,
  type PlateWindowAction,
  type PlateWindowSessionSnapshot,
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

export interface UseWindowCoordinatorOptions {
  state: EditorWorkspaceState;
  dispatch: React.Dispatch<EditorAction>;
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
  dispatch,
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
    dispatch({ type: 'set-render-profile', renderProfile: { compressionMode } });

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
  }, [activeFile, dispatch, sessionRevision, state]);

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
    buildPlateWindowSnapshot,
    buildAiPanelWindowSnapshot,
    state,
    sessionRevision,
    activeFile,
    currentIsPlaying,
    lprState,
    dispatch,
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
      buildPlateWindowSnapshot,
      buildAiPanelWindowSnapshot,
      state,
      sessionRevision,
      activeFile,
      currentIsPlaying,
      lprState,
      dispatch,
    };
  });

  // Listen to Plate Window events
  useEffect(() => {
    let disposed = false;
    let actionCleanup: (() => void) | undefined;
    let requestCleanup: (() => void) | undefined;

    void listen<PlateWindowAction>(PLATE_ACTION_EVENT, async (event) => {
      if (disposed) {
        return;
      }

      const actions = actionsRef.current;
      const action = event.payload;

      switch (action.type) {
        case 'refresh-runtime':
          await actions.refreshLprRuntimeStatus();
          break;
        case 'cancel-job':
          await actions.handleCancelLprJob();
          break;
        case 'use-clip-interval':
          actions.handleUseClipInterval();
          break;
        case 'set-interval-boundary':
          actions.handleSetIntervalBoundary(action.boundary);
          break;
        case 'clear-interval':
          actions.dispatch({ type: 'clear-lpr-interval' });
          break;
        case 'set-analysis-profile':
          actions.dispatch({ type: 'set-lpr-analysis-profile', analysisProfileId: action.analysisProfileId });
          break;
        case 'set-country-hints':
          latestCountryHintDraftRef.current = action.value;
          actions.applyCountryHints(action.value);
          break;
        case 'scan-targets':
          await actions.handleScanLprTargets();
          break;
        case 'analyze-frame':
          await actions.handleAnalyzeLprFrame();
          break;
        case 'analyze-range':
          await actions.handleAnalyzeLprInterval();
          break;
        case 'toggle-dense-sampling':
          actions.dispatch({ type: 'set-lpr-toggles', toggles: { useDenseSampling: !actions.lprState.useDenseSampling } });
          break;
        case 'toggle-developer-diagnostics':
          actions.dispatch({ type: 'set-lpr-toggles', toggles: { showDeveloperDiagnostics: !actions.lprState.showDeveloperDiagnostics } });
          break;
        case 'export-evidence':
          await actions.handleExportLprEvidence();
          break;
        case 'clear-results':
          actions.dispatch({ type: 'clear-lpr-results' });
          break;
        case 'select-target-track':
          actions.handleSelectTargetTrack(action.targetTrackId, action.anchorTimeMs);
          break;
        case 'accept-candidate':
          actions.dispatch({ type: 'accept-lpr-candidate', candidateId: action.candidateId });
          break;
        case 'seek-to-sample':
          actions.dispatch({ type: 'set-playhead', playheadMs: Math.max(0, Math.round(action.timeMs)) });
          if (actions.currentIsPlaying) {
            actions.dispatch({ type: 'set-playing', isPlaying: false });
          }
          break;
        default:
          break;
      }
    }).then((unlisten) => {
      actionCleanup = unlisten;
    });

    void listen(PLATE_SESSION_REQUEST_EVENT, async () => {
      if (disposed) {
        return;
      }
      plateWindowLiveSyncEnabledRef.current = true;
      const actions = actionsRef.current;
      await emitPlateWindowSession(actions.buildPlateWindowSnapshot(), actions.sessionRevision).catch(() => undefined);
    }).then((unlisten) => {
      requestCleanup = unlisten;
    });

    return () => {
      disposed = true;
      actionCleanup?.();
      requestCleanup?.();
    };
  }, [latestCountryHintDraftRef, plateWindowLiveSyncEnabledRef]);

  // Listen to AI Panel & Export Window events
  useEffect(() => {
    let disposed = false;
    let exportRequestCleanup: (() => void) | undefined;
    let actionCleanup: (() => void) | undefined;
    let requestCleanup: (() => void) | undefined;

    void listen<AiPanelAction>(AI_PANEL_ACTION_EVENT, async (event) => {
      if (disposed) {
        return;
      }

      const actions = actionsRef.current;
      const action = event.payload;

      switch (action.type) {
        case 'run-analysis':
          await actions.handleRunAiEvidence(action.prompt);
          break;
        case 'cancel-job':
          await actions.handleCancelAiJob();
          break;
        case 'seek-to-time':
          actions.dispatch({ type: 'set-playhead', playheadMs: Math.max(0, Math.round(action.timeMs)) });
          if (actions.currentIsPlaying) {
            actions.dispatch({ type: 'set-playing', isPlaying: false });
          }
          break;
        case 'reset-session':
          if (actions.activeFile) {
            actions.dispatch({ type: 'reset-ai-session', fileId: actions.activeFile.id });
          }
          break;
        default:
          break;
      }
    }).then((unlisten) => {
      actionCleanup = unlisten;
    });

    void listen(AI_PANEL_SESSION_REQUEST_EVENT, async () => {
      if (disposed) {
        return;
      }
      const actions = actionsRef.current;
      await emitAiPanelWindowSession(actions.buildAiPanelWindowSnapshot(), actions.sessionRevision).catch(() => undefined);
    }).then((unlisten) => {
      requestCleanup = unlisten;
    });

    void listen(EXPORT_SESSION_REQUEST_EVENT, async () => {
      if (disposed) {
        return;
      }
      const actions = actionsRef.current;
      try {
        const snapshot = preparePendingExportSession(actions.state);
        await syncExportWindowSession(snapshot, actions.sessionRevision).catch(() => undefined);
      } catch {
        // Ignore export-session requests when no exportable timeline is available.
      }
    }).then((unlisten) => {
      exportRequestCleanup = unlisten;
    });

    return () => {
      disposed = true;
      exportRequestCleanup?.();
      actionCleanup?.();
      requestCleanup?.();
    };
  }, []);

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
