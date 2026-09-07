/**
 * AI evidence use-case ports (Blueprint §4, Phase 4-B).
 *
 * The seam between pure AI-evidence use-cases and the outside world.
 * Every `runX(input, ports = defaultAiPorts)` use-case reads state, calls
 * infrastructure, and dispatches store actions exclusively through this
 * interface, so tests inject fake ports while production uses
 * {@link defaultAiPorts} (real infra API + `useEditorStore.getState()`).
 *
 * This file is the ONLY place in `usecases/` allowed to touch the store,
 * the infrastructure APIs, the logger, and id/time factories. Use-case
 * files must never import `bindings.commands` nor subscribe to React state.
 */
import { analyzeAiEvidence } from '../../infrastructure/aiEvidenceApi';
import { cancelLprRuntimeJob, getLprRuntimeStatus } from '../../infrastructure/lprApi';
import { useEditorStore } from '../store/store';
import { createId, createRunFolderId } from '../../domain/model';
import {
  createLogger,
  getErrorMessage,
  getErrorSummary,
  serializeError,
} from '../../../../utils/logger';
import type { EditorAnalysisState } from '../../domain/analysisState';
import type {
  AiEvidenceJobState,
  AiEvidenceRequest,
  AiEvidenceResponse,
} from '../../domain/aiEvidenceState';
import type { LprRuntimeStatus, LprSessionState } from '../../domain/lprState';

/** Unified use-case result: success carries data, failure carries a UI-safe message. */
export type AiEvidenceResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

export function aiOk<T>(data: T): AiEvidenceResult<T> {
  return { ok: true, data };
}

export function aiErr<T>(error: string): AiEvidenceResult<T> {
  return { ok: false, error };
}

/** In-flight AI evidence request tracked to ignore stale async completions. */
export interface ActiveAiRequest {
  requestId: string;
  fileId: string;
}

/**
 * Store action surface an AI-evidence use-case may dispatch.
 * Structural subset of `EditorStore` so fakes stay trivial.
 */
export interface AiEvidenceStoreActions {
  setAiPrompt: (fileId: string, prompt: string) => void;
  setAiJob: (fileId: string, job: Partial<AiEvidenceJobState>) => void;
  setAiResult: (fileId: string, result: AiEvidenceResponse | null) => void;
  replaceLprSession: (fileId: string, session: LprSessionState) => void;
  setLprRuntimeStatus: (runtime: LprRuntimeStatus | null) => void;
}

export interface AiEvidencePorts {
  /** Infrastructure: run the AI evidence pipeline for one request. */
  analyze: (request: AiEvidenceRequest) => Promise<AiEvidenceResponse>;
  /** Infrastructure: ask the runtime to cancel the current job. */
  cancelJob: () => Promise<boolean>;
  /** Read a snapshot of the editor analysis state (sessions by file). */
  readAnalysis: () => EditorAnalysisState;
  /** Active-request holder used for stale-completion guards. */
  getActiveRequest: () => ActiveAiRequest | null;
  setActiveRequest: (request: ActiveAiRequest) => void;
  clearActiveRequest: (requestId: string) => void;
  /** Store dispatches (via `useEditorStore.getState()` in production). */
  actions: AiEvidenceStoreActions;
  /** Surface a workspace-level message (hook wires its `setWorkspaceFeedback`). */
  notifyFeedback: (message: string | null) => void;
  /** Re-read the LPR runtime status into the store (never throws). */
  refreshRuntimeStatus: () => Promise<void>;
  /** Summarize an unknown error for UI display. */
  describeError: (error: unknown, fallback: string) => string;
  /** Structured log of a use-case failure. */
  logError: (message: string, error: unknown) => void;
  /** Current timestamp (ISO). Injected for deterministic tests. */
  now: () => string;
  /** Fresh request id for a new analysis run. */
  createRequestId: () => string;
  /** Fresh id for an LPR history entry projected from AI evidence. */
  createHistoryId: () => string;
}

const defaultAiLogger = createLogger('aiEvidenceUsecases');

let defaultActiveAiRequest: ActiveAiRequest | null = null;

/**
 * Production ports: real infra API + `useEditorStore.getState()` actions.
 * `notifyFeedback` has no store channel (feedback lives in React state in
 * `MainWorkspace`), so it logs; Wave 2 hooks override it with their
 * `setWorkspaceFeedback` callback.
 */
export const defaultAiPorts: AiEvidencePorts = {
  analyze: (request) => analyzeAiEvidence(request),
  cancelJob: () => cancelLprRuntimeJob(),
  readAnalysis: () => useEditorStore.getState().workspace.analysis,
  getActiveRequest: () => defaultActiveAiRequest,
  setActiveRequest: (request) => {
    defaultActiveAiRequest = request;
  },
  clearActiveRequest: (requestId) => {
    if (defaultActiveAiRequest?.requestId === requestId) {
      defaultActiveAiRequest = null;
    }
  },
  actions: {
    setAiPrompt: (fileId, prompt) => {
      useEditorStore.getState().setAiPrompt(fileId, prompt);
    },
    setAiJob: (fileId, job) => {
      useEditorStore.getState().setAiJob(fileId, job);
    },
    setAiResult: (fileId, result) => {
      useEditorStore.getState().setAiResult(fileId, result);
    },
    replaceLprSession: (fileId, session) => {
      useEditorStore.getState().replaceLprSession(fileId, session);
    },
    setLprRuntimeStatus: (runtime) => {
      useEditorStore.getState().setLprRuntimeStatus(runtime);
    },
  },
  notifyFeedback: (message) => {
    if (message === null) {
      defaultAiLogger.debug('AI evidence feedback cleared.');
      return;
    }
    defaultAiLogger.warn(`AI evidence feedback: ${message}`);
  },
  refreshRuntimeStatus: async () => {
    try {
      const runtimeStatus = await getLprRuntimeStatus();
      useEditorStore.getState().setLprRuntimeStatus(runtimeStatus);
    } catch (error) {
      useEditorStore.getState().setLprRuntimeStatus({
        available: false,
        pythonExecutable: null,
        runtimeScript: null,
        version: null,
        missingPackages: [],
        installedPackages: [],
        detail: getErrorMessage(error, 'Unable to inspect the local LPR runtime.'),
      });
    }
  },
  describeError: (error, fallback) => getErrorSummary(error, fallback),
  logError: (message, error) => {
    defaultAiLogger.error(message, serializeError(error));
  },
  now: () => new Date().toISOString(),
  createRequestId: () => createRunFolderId(),
  createHistoryId: () => createId('lpr-history'),
};
