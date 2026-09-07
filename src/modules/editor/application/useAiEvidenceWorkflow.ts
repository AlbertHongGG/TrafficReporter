import { useCallback, useEffect, useMemo, useRef } from 'react';
import { listen } from '@tauri-apps/api/event';
import type { EditorWorkspaceState, EditorFileState } from '../domain/model';
import { useEditorStore } from './store/store';
import { getAiEvidenceSessionByFileId, getLprSessionByFileId } from '../domain/analysisState';
import { buildDefaultLprState, buildLprTargetAnchor } from '../domain/lprState';
import { analyzeAiEvidence } from '../infrastructure/aiEvidenceApi';
import { cancelLprRuntimeJob } from '../infrastructure/lprApi';
import { createLogger, getErrorSummary, serializeError } from '../../../utils/logger';
import { buildAiEvidenceProjectionDetail, resolveStageStartedAt } from '../domain/lprWorkflowHelpers';
import { createId, createRunFolderId } from '../domain/model';
import type {
  AiEvidenceProgress,
  AiEvidenceResponse,
  AiEvidenceSessionState,
  LprSessionState,
  LprTargetTrack,
  LprVehicleKind,
} from '../domain/model';

const log = createLogger('useAiEvidenceWorkflow');

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
  lprState,
  lprAnalysisVehicleKind,
  refreshLprRuntimeStatus,
  setWorkspaceFeedback,
}: UseAiEvidenceWorkflowOptions) {
  const activeAiRequestRef = useRef<{ requestId: string; fileId: string } | null>(null);

  const aiState = useMemo(
    () => getAiEvidenceSessionByFileId(state.analysis, activeFile?.id ?? null),
    [activeFile?.id, state.analysis],
  );
  const aiJob = aiState.job;
  const aiBusy = aiJob.status === 'queued' || aiJob.status === 'running';

  const updateAiJob = useCallback((fileId: string, job: Partial<AiEvidenceSessionState['job']>) => {
    const timestamp = new Date().toISOString();
    const currentJob = getAiEvidenceSessionByFileId(state.analysis, fileId).job;
    useEditorStore.getState().setAiJob(fileId, {
      ...job,
      stageStartedAt: resolveStageStartedAt(currentJob, job, timestamp),
      updatedAt: timestamp,
    });
  }, [state.analysis]);

  const beginAiRequest = useCallback((fileId: string, prompt: string) => {
    const requestId = createRunFolderId();
    activeAiRequestRef.current = { requestId, fileId };
    const store = useEditorStore.getState();
    store.setAiPrompt(fileId, prompt);
    store.setAiResult(fileId, null);
    updateAiJob(fileId, {
      status: 'running',
      progress: 0.05,
      stage: 'Prepare',
      detail: 'Preparing AI evidence workflow.',
      requestId,
      error: null,
      startedAt: new Date().toISOString(),
      progressKind: 'host-step',
      toolName: null,
      toolLabel: null,
      stepIndex: 1,
      stepCount: 11,
      stageStepIndex: 1,
      stageStepCount: 1,
    });
    return requestId;
  }, [updateAiJob]);

  const forgetAiRequest = useCallback((requestId: string) => {
    if (activeAiRequestRef.current?.requestId === requestId) {
      activeAiRequestRef.current = null;
    }
  }, []);

  const applyAiEvidenceProjection = useCallback((fileId: string, response: AiEvidenceResponse) => {
    const currentLprState = getLprSessionByFileId(state.analysis, fileId);
    const acceptedCandidateId = response.projection.acceptedCandidateId ?? null;
    const projectedTargetTracks = response.projection.targetTracks;
    const selectedTargetTrackId = response.projection.selectedTargetTrackId
      ?? response.targetSelection?.selectedTrackId
      ?? response.projection.analysisTrack?.id
      ?? currentLprState.selectedTargetTrackId;
    const projectedSelectedTrack = projectedTargetTracks.find((track: LprTargetTrack) => track.id === selectedTargetTrackId) ?? null;
    const selectedTargetAnchor = projectedSelectedTrack
      ? buildLprTargetAnchor(projectedSelectedTrack, response.primaryAnchor?.timeMs ?? currentLprState.selectedTargetAnchor?.timeMs ?? null)
      : response.projection.analysisTrack
        ? buildLprTargetAnchor(response.projection.analysisTrack, response.primaryAnchor?.timeMs ?? response.projection.interval?.startMs ?? null)
        : currentLprState.selectedTargetAnchor;
    const projectionDetail = buildAiEvidenceProjectionDetail(
      response.projection.candidates,
      response.projection.review,
      projectedTargetTracks,
    );
    const projectedSession = buildDefaultLprState({
      ...currentLprState,
      workflowMode: response.projection.candidates.length > 0 ? 'review' : 'target',
      interval: response.projection.interval ?? currentLprState.interval,
      targetTracks: projectedTargetTracks,
      selectedTargetTrackId,
      selectedTargetAnchor,
      analysisTrack: response.projection.analysisTrack ?? null,
      samples: response.projection.samples,
      candidates: response.projection.candidates,
      review: response.projection.review ?? null,
      lastAnalysisProvenance: response.projection.provenance ?? null,
      decision: response.projection.decision ?? null,
      acceptedCandidateId,
      job: {
        ...currentLprState.job,
        status: 'completed',
        progress: 1,
        stage: 'AI evidence',
        detail: projectionDetail,
        requestId: response.requestId ?? currentLprState.job.requestId,
        error: null,
        updatedAt: new Date().toISOString(),
      },
      history: response.projection.candidates.length > 0
        ? [...currentLprState.history, {
          id: createId('lpr-history'),
          createdAt: new Date().toISOString(),
          interval: response.projection.interval ?? null,
          targetTrackId: selectedTargetTrackId ?? response.projection.analysisTrack?.id ?? null,
          acceptedCandidateId,
          analysisProfileId: currentLprState.selectedAnalysisProfileId,
          developerDiagnosticsEnabled: currentLprState.showDeveloperDiagnostics,
          candidates: response.projection.candidates,
          summary: response.summary,
        }]
        : currentLprState.history,
    });
    useEditorStore.getState().replaceLprSession(fileId, projectedSession);
  }, [state.analysis]);

  const handleCancelAiJob = useCallback(async () => {
    const activeRequest = activeAiRequestRef.current;
    if (!activeRequest) {
      return;
    }

    updateAiJob(activeRequest.fileId, {
      status: 'cancelled',
      stage: aiState.job.stage || 'AI evidence',
      detail: 'Cancelling current AI evidence task.',
      error: null,
    });

    try {
      await cancelLprRuntimeJob();
      activeAiRequestRef.current = null;
      updateAiJob(activeRequest.fileId, {
        status: 'cancelled',
        progress: 1,
        stage: aiState.job.stage || 'AI evidence',
        detail: 'Current AI evidence task cancelled.',
        error: null,
      });
      await refreshLprRuntimeStatus();
    } catch (error) {
      const summary = getErrorSummary(error, 'Unable to cancel the current AI evidence task.');
      updateAiJob(activeRequest.fileId, {
        status: 'failed',
        progress: 1,
        stage: aiState.job.stage || 'AI evidence',
        detail: 'Unable to cancel the current AI evidence task.',
        error: summary,
      });
      setWorkspaceFeedback(summary);
    }
  }, [aiState.job.stage, refreshLprRuntimeStatus, setWorkspaceFeedback, updateAiJob]);

  const handleRunAiEvidence = useCallback(async (prompt: string) => {
    if (!activeFile || activeFile.asset.status !== 'ready') {
      return;
    }

    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      setWorkspaceFeedback('AI evidence analysis requires a natural-language description.');
      return;
    }

    const fileId = activeFile.id;
    const requestId = beginAiRequest(fileId, trimmedPrompt);
    setWorkspaceFeedback(null);

    try {
      const response = await analyzeAiEvidence({
        sourcePath: activeFile.asset.path,
        description: trimmedPrompt,
        markerRect: activeFile.markerRect,
        compressionMode: activeFile.renderProfile.compressionMode,
        audioBitrateKbps: activeFile.renderProfile.audioBitrateKbps,
        targetVehicleKind: lprAnalysisVehicleKind ?? 'any',
        countryHints: lprState.countryHints,
        analysisProfileId: lprState.selectedAnalysisProfileId,
        enableDeveloperDiagnostics: lprState.showDeveloperDiagnostics,
        requestId,
      });

      if (activeAiRequestRef.current?.requestId !== requestId || activeAiRequestRef.current?.fileId !== fileId) {
        return;
      }

      const store = useEditorStore.getState();
      store.setLprRuntimeStatus(response.runtime);
      store.setAiResult(fileId, response);
      updateAiJob(fileId, {
        status: 'completed',
        progress: 1,
        stage: 'Completed',
        detail: response.summary,
        error: null,
        requestId,
        progressKind: 'host-step',
        toolName: null,
        toolLabel: null,
        stepIndex: 11,
        stepCount: 11,
        stageStepIndex: 1,
        stageStepCount: 1,
      });
      applyAiEvidenceProjection(fileId, response);
    } catch (error) {
      if (activeAiRequestRef.current?.requestId !== requestId || activeAiRequestRef.current?.fileId !== fileId) {
        return;
      }
      log.error('AI evidence analysis failed.', serializeError(error));
      const summary = getErrorSummary(error, 'Unable to run the AI evidence workflow.');
      updateAiJob(fileId, {
        status: 'failed',
        progress: 1,
        stage: 'Failed',
        detail: 'AI evidence analysis failed.',
        error: summary,
        requestId,
        progressKind: 'host-step',
        toolName: null,
        toolLabel: null,
        stepIndex: 11,
        stepCount: 11,
        stageStepIndex: 1,
        stageStepCount: 1,
      });
      setWorkspaceFeedback(summary);
    } finally {
      forgetAiRequest(requestId);
    }
  }, [
    activeFile,
    applyAiEvidenceProjection,
    beginAiRequest,
    forgetAiRequest,
    lprAnalysisVehicleKind,
    lprState.countryHints,
    lprState.selectedAnalysisProfileId,
    lprState.showDeveloperDiagnostics,
    setWorkspaceFeedback,
    updateAiJob,
  ]);

  // Listen to AI Evidence Progress Events
  useEffect(() => {
    let disposed = false;
    let progressCleanup: (() => void) | undefined;

    void listen<AiEvidenceProgress>('editor/ai-evidence-progress', (event) => {
      if (disposed) {
        return;
      }

      const activeRequest = activeAiRequestRef.current;
      if (!activeRequest) {
        return;
      }

      if (event.payload.requestId && event.payload.requestId !== activeRequest.requestId) {
        return;
      }

      updateAiJob(activeRequest.fileId, {
        status: event.payload.failed ? 'failed' : event.payload.done ? 'completed' : 'running',
        progress: Math.max(0, Math.min(1, event.payload.progress)),
        stage: event.payload.stage,
        detail: event.payload.detail,
        requestId: activeRequest.requestId,
        error: event.payload.failed ? event.payload.detail : null,
        progressKind: event.payload.progressKind ?? null,
        toolName: event.payload.toolName ?? null,
        toolLabel: event.payload.toolLabel ?? null,
        stepIndex: event.payload.stepIndex ?? null,
        stepCount: event.payload.stepCount ?? null,
        stageStepIndex: event.payload.stageStepIndex ?? null,
        stageStepCount: event.payload.stageStepCount ?? null,
      });
    }).then((unlisten) => {
      progressCleanup = unlisten;
    });

    return () => {
      disposed = true;
      progressCleanup?.();
    };
  }, [updateAiJob]);

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
