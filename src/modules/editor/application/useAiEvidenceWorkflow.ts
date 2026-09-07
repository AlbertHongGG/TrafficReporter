/**
 * AI evidence workflow hook — React glue (Blueprint §4, Phase 4-D).
 *
 * Slim surface: subscribes to the workspace snapshot via props, derives the
 * AI job view-model, and forwards UI events to the AI-evidence use-cases
 * through `AiEvidencePorts` (`notifyFeedback` overridden with the workspace
 * feedback callback; in-flight request tracking stays on this hook's ref so
 * stale completions are ignored per instance). All business decisions live
 * in `usecases/aiEvidence*.usecase.ts`; the `editor/ai-evidence-progress`
 * subscription below only maps events into `runAiEvidenceProgress`.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { listen } from '@tauri-apps/api/event';
import type { EditorWorkspaceState, EditorFileState } from '../domain/model';
import { getAiEvidenceSessionByFileId } from '../domain/analysisState';
import type {
  AiEvidenceProgress,
  AiEvidenceResponse,
  AiEvidenceSessionState,
  LprSessionState,
  LprVehicleKind,
} from '../domain/model';
import { defaultAiPorts, type ActiveAiRequest, type AiEvidencePorts } from './usecases/aiEvidencePorts.usecase';
import { runAiEvidenceJobUpdate, runAiEvidenceProgress, runAiEvidenceCancel } from './usecases/aiEvidenceJob.usecase';
import { runAiEvidenceBegin, runAiEvidenceAnalysis } from './usecases/aiEvidenceAnalysis.usecase';
import { runAiEvidenceProjection } from './usecases/aiEvidenceProjection.usecase';

export interface UseAiEvidenceWorkflowOptions {
  state: EditorWorkspaceState;
  activeFile: EditorFileState | null | undefined;
  lprState: LprSessionState;
  lprAnalysisVehicleKind: LprVehicleKind | null;
  refreshLprRuntimeStatus: () => Promise<void>;
  setWorkspaceFeedback: (message: string | null) => void;
}

export function useAiEvidenceWorkflow({
  state,
  activeFile,
  // `lprState` / `lprAnalysisVehicleKind` stay on `UseAiEvidenceWorkflowOptions`
  // for signature stability; the analysis use-case reads the LPR session
  // through `aiPorts.readAnalysis`, while the vehicle-kind hint is forwarded
  // explicitly in `handleRunAiEvidence`.
  lprAnalysisVehicleKind,
  refreshLprRuntimeStatus,
  setWorkspaceFeedback,
}: UseAiEvidenceWorkflowOptions) {
  const activeAiRequestRef = useRef<ActiveAiRequest | null>(null);

  const aiPorts = useMemo<AiEvidencePorts>(() => ({
    ...defaultAiPorts,
    getActiveRequest: () => activeAiRequestRef.current,
    setActiveRequest: (request) => {
      activeAiRequestRef.current = request;
    },
    clearActiveRequest: (requestId) => {
      if (activeAiRequestRef.current?.requestId === requestId) {
        activeAiRequestRef.current = null;
      }
    },
    notifyFeedback: (message) => {
      setWorkspaceFeedback(message);
    },
    refreshRuntimeStatus: () => refreshLprRuntimeStatus(),
  }), [refreshLprRuntimeStatus, setWorkspaceFeedback]);

  const aiState = useMemo(
    () => getAiEvidenceSessionByFileId(state.analysis, activeFile?.id ?? null),
    [activeFile?.id, state.analysis],
  );
  const aiJob = aiState.job;
  const aiBusy = aiJob.status === 'queued' || aiJob.status === 'running';

  const updateAiJob = useCallback((fileId: string, job: Partial<AiEvidenceSessionState['job']>) => {
    runAiEvidenceJobUpdate({ fileId, job }, aiPorts);
  }, [aiPorts]);

  const beginAiRequest = useCallback((fileId: string, prompt: string) => {
    const begun = runAiEvidenceBegin({ fileId, prompt }, aiPorts);
    return begun.ok ? begun.data.requestId : '';
  }, [aiPorts]);

  const forgetAiRequest = useCallback((requestId: string) => {
    aiPorts.clearActiveRequest(requestId);
  }, [aiPorts]);

  const applyAiEvidenceProjection = useCallback((fileId: string, response: AiEvidenceResponse) => {
    runAiEvidenceProjection({ fileId, response }, aiPorts);
  }, [aiPorts]);

  const handleCancelAiJob = useCallback(async () => {
    await runAiEvidenceCancel({}, aiPorts);
  }, [aiPorts]);

  const handleRunAiEvidence = useCallback(async (prompt: string) => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    await runAiEvidenceAnalysis({
      fileId: activeFile.id,
      sourcePath: activeFile.asset.path,
      assetReady: true,
      prompt,
      markerRect: activeFile.markerRect,
      compressionMode: activeFile.renderProfile.compressionMode,
      audioBitrateKbps: activeFile.renderProfile.audioBitrateKbps,
      targetVehicleKind: lprAnalysisVehicleKind ?? 'any',
    }, aiPorts);
  }, [activeFile, aiPorts, lprAnalysisVehicleKind]);

  // AI evidence progress events → use-case → store (stale events ignored).
  useEffect(() => {
    let disposed = false;
    let progressCleanup: (() => void) | undefined;

    void listen<AiEvidenceProgress>('editor/ai-evidence-progress', (event) => {
      if (disposed) {
        return;
      }

      const activeRequest = aiPorts.getActiveRequest();
      if (!activeRequest) {
        return;
      }

      runAiEvidenceProgress({
        fileId: activeRequest.fileId,
        requestId: event.payload.requestId ?? activeRequest.requestId,
        progress: event.payload,
      }, aiPorts);
    }).then((unlisten) => {
      progressCleanup = unlisten;
    });

    return () => {
      disposed = true;
      progressCleanup?.();
    };
  }, [aiPorts]);

  return {
    aiState,
    aiJob,
    aiBusy,
    activeAiRequestRef,
    updateAiJob,
    beginAiRequest,
    forgetAiRequest,
    applyAiEvidenceProjection,
    handleCancelAiJob,
    handleRunAiEvidence,
  };
}
