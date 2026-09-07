/**
 * LPR use-case ports (Blueprint §4, Phase 4-A).
 *
 * The seam between pure LPR use-cases and the outside world. Every
 * `runX(input, ports = defaultLprPorts)` use-case reads snapshots, calls
 * infrastructure, and dispatches store actions exclusively through this
 * interface, so tests inject fake ports while production uses
 * {@link defaultLprPorts} (real infra API + `useEditorStore.getState()`).
 *
 * This file is the ONLY place in `usecases/lpr*` allowed to touch the store,
 * the infrastructure APIs, the logger, and id/time factories. LPR use-case
 * files must never import `bindings.commands` nor subscribe to React state.
 * Progress `listen()` subscriptions, file dialogs, and React `setState` stay
 * in the Wave 2 hook; the hook reaches use-cases through these ports
 * (overriding `notifyFeedback` with its `setWorkspaceFeedback` callback).
 */
import {
  analyzeLprFrame,
  analyzeLprInterval,
  cancelLprRuntimeJob,
  exportLprEvidence,
  getLprRuntimeStatus,
  scanLprTargets,
} from '../../infrastructure/lprApi';
import { IpcCommandError } from '../../../../infrastructure/ipc-unwrap';
import { EDITOR_ENV } from '../../config/editorEnv';
import { useEditorStore } from '../store/store';
import { getActiveFile } from '../../domain/model';
import { getLprSessionByFileId } from '../../domain/analysisState';
import { resolveStageStartedAt } from '../../domain/lprWorkflowHelpers';
import { createId, createRunFolderId } from '../../domain/model';
import {
  createLogger,
  getErrorSummary,
  serializeError,
} from '../../../../utils/logger';
import type {
  EditorFileState,
  LprDecisionTrace,
  LprJobStatus,
  TimelineIntervalSelection,
} from '../../domain/model';
import type {
  LprEvidenceExportRequest,
  LprEvidenceExportResponse,
  LprFrameAnalysisRequest,
  LprFrameAnalysisResponse,
  LprIntervalAnalysisRequest,
  LprIntervalAnalysisResponse,
  LprJobState,
  LprResultHistoryEntry,
  LprRuntimeStatus,
  LprSessionState,
  LprTargetAnchor,
  LprTargetTrack,
  LprFrameSample,
  LprPlateCandidate,
  LprReviewState,
  LprAnalysisProvenance,
  LprTargetScanRequest,
  LprTargetScanResponse,
  LprWorkflowMode,
} from '../../domain/lprState';

/** Failure kinds: `IpcCommandError` semantics plus use-case level guards. */
export type LprErrorKind = 'command' | 'transport' | 'validation' | 'stale' | 'skipped';

export interface LprUsecaseError {
  kind: LprErrorKind;
  command: string;
  message: string;
  reasonCode: string | null;
}

/** Unified use-case result: success carries data, failure carries structured error. */
export type LprResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: LprUsecaseError };

export function lprOk<T>(data: T): LprResult<T> {
  return { ok: true, data };
}

export function lprErr<T>(error: LprUsecaseError): LprResult<T> {
  return { ok: false, error };
}

export function lprValidationError(message: string, reasonCode: string | null = null, command = 'lpr-usecase'): LprUsecaseError {
  return { kind: 'validation', command, message, reasonCode };
}

export function lprSkipped(message: string, command = 'lpr-usecase'): LprUsecaseError {
  return { kind: 'skipped', command, message, reasonCode: null };
}

export function lprStaleError(requestId: string, command = 'lpr-usecase'): LprUsecaseError {
  return {
    kind: 'stale',
    command,
    message: `Superseded or cancelled LPR request ignored (${requestId}).`,
    reasonCode: null,
  };
}

/**
 * Map an unknown failure to {@link LprUsecaseError}, preserving
 * `IpcCommandError` kind/command semantics for backend vs transport faults.
 */
export function toLprUsecaseError(error: unknown, command: string, fallback: string, reasonCode: string | null = null): LprUsecaseError {
  if (error instanceof IpcCommandError) {
    return {
      kind: error.kind,
      command: error.command,
      message: getErrorSummary(error, fallback),
      reasonCode,
    };
  }
  return {
    kind: 'transport',
    command,
    message: getErrorSummary(error, fallback),
    reasonCode,
  };
}

/** Parse a comma-separated country-hint draft into clean codes. */
export function parseCountryHints(draftValue: string): string[] {
  return draftValue
    .split(',')
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
}

/**
 * Store action surface an LPR use-case may dispatch.
 * Structural subset of `EditorStore` so fakes stay trivial.
 */
export interface LprStoreActions {
  setLprRuntimeStatus: (runtimeStatus: LprRuntimeStatus | null) => void;
  setLprJob: (job: Partial<LprJobState>) => void;
  setLprTargetTracks: (targetTracks: LprTargetTrack[]) => void;
  setLprAnalysisTrack: (analysisTrack: LprTargetTrack | null) => void;
  setLprMode: (workflowMode: LprWorkflowMode) => void;
  setLprInterval: (interval: TimelineIntervalSelection) => void;
  setLprCountryHints: (countryHints: string[]) => void;
  selectLprTargetTrack: (targetTrackId: string | null, anchor: LprTargetAnchor | null) => void;
  setLprSamples: (samples: LprFrameSample[]) => void;
  setLprCandidates: (candidates: LprPlateCandidate[]) => void;
  setLprReview: (review: LprReviewState | null) => void;
  setLprProvenance: (provenance: LprAnalysisProvenance | null) => void;
  setLprDecision: (decision: LprDecisionTrace | null) => void;
  appendLprHistory: (entry: LprResultHistoryEntry) => void;
  setPlayhead: (playheadMs: number) => void;
  setPlaying: (isPlaying: boolean) => void;
}

export interface LprPorts {
  /** Infrastructure: scan the current frame for trackable targets. */
  scanTargets: (request: LprTargetScanRequest) => Promise<LprTargetScanResponse>;
  /** Infrastructure: analyze a single frame. */
  analyzeFrame: (request: LprFrameAnalysisRequest) => Promise<LprFrameAnalysisResponse>;
  /** Infrastructure: analyze the selected interval. */
  analyzeInterval: (request: LprIntervalAnalysisRequest) => Promise<LprIntervalAnalysisResponse>;
  /** Infrastructure: export the evidence bundle to a resolved path. */
  exportEvidence: (request: LprEvidenceExportRequest) => Promise<LprEvidenceExportResponse>;
  /** Infrastructure: inspect the local LPR runtime. */
  getRuntimeStatus: () => Promise<LprRuntimeStatus>;
  /** Infrastructure: ask the runtime to cancel the current job. */
  cancelRuntimeJob: () => Promise<boolean>;
  /** Snapshot of the active file (null when none). */
  readActiveFile: () => EditorFileState | null;
  /** Snapshot of the active file's LPR session. */
  readLprSession: () => LprSessionState;
  /** Whether the active file is currently playing. */
  readIsPlaying: () => boolean;
  /** In-flight request tracking (mirrors the hook's request refs). */
  getActiveRequestId: () => string | null;
  beginRequest: (stage: string, detail: string, progress: number) => string;
  isStale: (requestId: string) => boolean;
  markCancelled: (requestId: string) => void;
  isCancelled: (requestId: string) => boolean;
  unmarkCancelled: (requestId: string) => void;
  clearActiveRequest: (requestId: string) => void;
  forgetRequest: (requestId: string) => void;
  /** Store dispatches (via `useEditorStore.getState()` in production). */
  actions: LprStoreActions;
  /** Surface a workspace-level message (hook wires its `setWorkspaceFeedback`). */
  notifyFeedback: (message: string | null) => void;
  /** Summarize an unknown error for UI display. */
  describeError: (error: unknown, fallback: string) => string;
  /** Structured log of a use-case failure. */
  logError: (message: string, error: unknown) => void;
  /** Current timestamp (ISO). Injected for deterministic tests. */
  now: () => string;
  /** Fresh request id for a new LPR run. */
  createRequestId: () => string;
  /** Fresh id for an LPR history entry. */
  createHistoryId: () => string;
  /** Overlay tolerance for resolving the selected target box. */
  overlayToleranceMs: number;
}

const defaultLprLogger = createLogger('lprUsecases');

let defaultActiveLprRequestId: string | null = null;
const defaultCancelledLprRequestIds = new Set<string>();

function readDefaultWorkspace() {
  return useEditorStore.getState().workspace;
}

function readDefaultJob(): LprJobState {
  const workspace = readDefaultWorkspace();
  return getLprSessionByFileId(workspace.analysis, workspace.activeFileId).job;
}

/**
 * Production ports: real infra API + `useEditorStore.getState()` actions.
 * `notifyFeedback` has no store channel (feedback lives in React state in
 * `MainWorkspace`), so it logs; Wave 2 hooks override it with their
 * `setWorkspaceFeedback` callback.
 */
export const defaultLprPorts: LprPorts = {
  scanTargets: (request) => scanLprTargets(request),
  analyzeFrame: (request) => analyzeLprFrame(request),
  analyzeInterval: (request) => analyzeLprInterval(request),
  exportEvidence: (request) => exportLprEvidence(request),
  getRuntimeStatus: () => getLprRuntimeStatus(),
  cancelRuntimeJob: () => cancelLprRuntimeJob(),
  readActiveFile: () => getActiveFile(readDefaultWorkspace()),
  readLprSession: () => {
    const workspace = readDefaultWorkspace();
    return getLprSessionByFileId(workspace.analysis, workspace.activeFileId);
  },
  readIsPlaying: () => getActiveFile(readDefaultWorkspace())?.isPlaying ?? false,
  getActiveRequestId: () => defaultActiveLprRequestId,
  beginRequest: (stage, detail, progress) => {
    const requestId = createRunFolderId();
    const timestamp = new Date().toISOString();
    defaultActiveLprRequestId = requestId;
    defaultCancelledLprRequestIds.delete(requestId);
    const currentJob = readDefaultJob();
    const patch = {
      status: 'running' as LprJobStatus,
      requestId,
      progress,
      stage,
      detail,
      error: null,
      reasonCode: null,
      startedAt: timestamp,
      trackingTier: null,
      coverageRatio: null,
    };
    useEditorStore.getState().setLprJob({
      ...patch,
      stageStartedAt: resolveStageStartedAt(currentJob, patch, timestamp),
      updatedAt: timestamp,
    });
    return requestId;
  },
  isStale: (requestId) => (
    defaultActiveLprRequestId !== requestId || defaultCancelledLprRequestIds.has(requestId)
  ),
  markCancelled: (requestId) => {
    defaultCancelledLprRequestIds.add(requestId);
  },
  isCancelled: (requestId) => defaultCancelledLprRequestIds.has(requestId),
  unmarkCancelled: (requestId) => {
    defaultCancelledLprRequestIds.delete(requestId);
  },
  clearActiveRequest: (requestId) => {
    if (defaultActiveLprRequestId === requestId) {
      defaultActiveLprRequestId = null;
    }
  },
  forgetRequest: (requestId) => {
    if (defaultActiveLprRequestId === requestId) {
      defaultActiveLprRequestId = null;
    }
    defaultCancelledLprRequestIds.delete(requestId);
  },
  actions: {
    setLprRuntimeStatus: (runtimeStatus) => {
      useEditorStore.getState().setLprRuntimeStatus(runtimeStatus);
    },
    setLprJob: (job) => {
      useEditorStore.getState().setLprJob(job);
    },
    setLprTargetTracks: (targetTracks) => {
      useEditorStore.getState().setLprTargetTracks(targetTracks);
    },
    setLprAnalysisTrack: (analysisTrack) => {
      useEditorStore.getState().setLprAnalysisTrack(analysisTrack);
    },
    setLprMode: (workflowMode) => {
      useEditorStore.getState().setLprMode(workflowMode);
    },
    setLprInterval: (interval) => {
      useEditorStore.getState().setLprInterval(interval);
    },
    setLprCountryHints: (countryHints) => {
      useEditorStore.getState().setLprCountryHints(countryHints);
    },
    selectLprTargetTrack: (targetTrackId, anchor) => {
      useEditorStore.getState().selectLprTargetTrack(targetTrackId, anchor);
    },
    setLprSamples: (samples) => {
      useEditorStore.getState().setLprSamples(samples);
    },
    setLprCandidates: (candidates) => {
      useEditorStore.getState().setLprCandidates(candidates);
    },
    setLprReview: (review) => {
      useEditorStore.getState().setLprReview(review);
    },
    setLprProvenance: (provenance) => {
      useEditorStore.getState().setLprProvenance(provenance);
    },
    setLprDecision: (decision) => {
      useEditorStore.getState().setLprDecision(decision);
    },
    appendLprHistory: (entry) => {
      useEditorStore.getState().appendLprHistory(entry);
    },
    setPlayhead: (playheadMs) => {
      useEditorStore.getState().setPlayhead(playheadMs);
    },
    setPlaying: (isPlaying) => {
      useEditorStore.getState().setPlaying(isPlaying);
    },
  },
  notifyFeedback: (message) => {
    if (message === null) {
      defaultLprLogger.debug('LPR feedback cleared.');
      return;
    }
    defaultLprLogger.warn(`LPR feedback: ${message}`);
  },
  describeError: (error, fallback) => getErrorSummary(error, fallback),
  logError: (message, error) => {
    defaultLprLogger.error(message, serializeError(error));
  },
  now: () => new Date().toISOString(),
  createRequestId: () => createRunFolderId(),
  createHistoryId: () => createId('lpr-history'),
  overlayToleranceMs: EDITOR_ENV.lprTargetOverlayToleranceMs,
};

/**
 * Shared job-commit helper: applies a partial job patch with stage-clock and
 * updated-at bookkeeping (mirrors the hook's `updateLprJob`).
 */
export function commitLprJobUpdate(ports: LprPorts, patch: Partial<LprJobState>): void {
  const timestamp = ports.now();
  const currentJob = ports.readLprSession().job;
  ports.actions.setLprJob({
    ...patch,
    stageStartedAt: resolveStageStartedAt(currentJob, patch, timestamp),
    updatedAt: timestamp,
  });
}

/** Readiness guard shared by scan/frame/interval/export use-cases. */
export function readReadyFile(ports: LprPorts): EditorFileState | null {
  const file = ports.readActiveFile();
  if (!file || file.asset.status !== 'ready') {
    return null;
  }
  return file;
}
