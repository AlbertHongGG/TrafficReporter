/**
 * AI evidence use-cases tests (Phase 4-B).
 *
 * All use-cases run against fake ports: no store, no infrastructure, no
 * timers. Covers happy paths plus error/stale paths for every use-case.
 */
import { describe, expect, it, vi } from 'vitest';
import {
  buildDefaultAnalysisState,
  type EditorAnalysisState,
} from '../../domain/analysisState';
import {
  buildDefaultAiEvidenceState,
  DEFAULT_AI_EVIDENCE_JOB_STATE,
  type AiEvidenceJobState,
  type AiEvidenceProgress,
  type AiEvidenceResponse,
  type AiEvidenceTargetSelection,
  type AiEvidenceTimelineFrameRef,
} from '../../domain/aiEvidenceState';
import {
  buildDefaultLprState,
  type LprPlateCandidate,
  type LprRuntimeStatus,
  type LprSessionState,
  type LprTargetTrack,
} from '../../domain/lprState';
import {
  runAiEvidenceAnalysis,
  runAiEvidenceBegin,
  runAiEvidenceComplete,
  runAiEvidenceFail,
} from './aiEvidenceAnalysis.usecase';
import {
  runAiEvidenceCancel,
  runAiEvidenceJobUpdate,
  runAiEvidenceProgress,
} from './aiEvidenceJob.usecase';
import { runAiEvidenceProjection } from './aiEvidenceProjection.usecase';
import type {
  ActiveAiRequest,
  AiEvidencePorts,
} from './aiEvidencePorts.usecase';

const FILE_ID = 'file-1';
const NOW = '2026-01-02T03:04:05.000Z';

const RUNTIME: LprRuntimeStatus = {
  available: true,
  pythonExecutable: 'python',
  runtimeScript: 'run.py',
  version: '1.0',
  missingPackages: [],
  installedPackages: ['engine'],
  detail: 'runtime ready',
};

function seedAnalysis(options: {
  aiJob?: AiEvidenceJobState;
  lpr?: LprSessionState;
} = {}): EditorAnalysisState {
  return buildDefaultAnalysisState({
    lprSessionsByFileId: { [FILE_ID]: options.lpr ?? buildDefaultLprState() },
    aiEvidenceSessionsByFileId: {
      [FILE_ID]: buildDefaultAiEvidenceState(options.aiJob ? { job: options.aiJob } : {}),
    },
  });
}

function makeFrameRef(timeMs: number): AiEvidenceTimelineFrameRef {
  return {
    frameId: `frame-${timeMs}`,
    timeMs,
    sequenceIndex: 1,
    label: `frame ${timeMs}`,
    imagePath: null,
    frameWidth: 640,
    frameHeight: 480,
  };
}

function makeTrack(id: string, timeMs: number): LprTargetTrack {
  return {
    id,
    className: 'car',
    label: `car ${id}`,
    confidence: 0.9,
    frames: [
      {
        id: `region-${id}`,
        timeMs,
        box: { x: 0.1, y: 0.1, width: 0.4, height: 0.3 },
        confidence: 0.9,
        className: 'car',
      },
    ],
  };
}

function makeCandidate(id: string, text: string): LprPlateCandidate {
  return {
    id,
    text,
    confidence: 0.88,
    source: 'ocr',
    frameTimeMs: 500,
    countryCode: null,
    box: null,
    quality: null,
  };
}

function makeSelection(trackId: string): AiEvidenceTargetSelection {
  return {
    anchorFrameId: 'frame-500',
    selectedTrackId: trackId,
    selectedCandidateId: null,
    confidence: 0.7,
    rationale: 'closest match',
    selectedBox: null,
  };
}

function makeResponse(overrides: Partial<AiEvidenceResponse> = {}): AiEvidenceResponse {
  return {
    requestId: 'req-1',
    description: 'find the plate',
    summary: 'summary text',
    provider: 'mock',
    interval: { startMs: 0, endMs: 1000 },
    plateNumber: 'ABC123',
    plateCandidate: null,
    primaryAnchor: null,
    targetSelection: null,
    keyframes: [],
    keyframeCountReason: null,
    toolCalls: [],
    projection: {
      interval: null,
      targetTracks: [],
      analysisTrack: null,
      selectedTargetTrackId: null,
      samples: [],
      candidates: [],
      acceptedCandidateId: null,
      review: null,
      provenance: null,
      decision: null,
    },
    clipPath: null,
    runtime: RUNTIME,
    ...overrides,
  };
}

function makeProgress(overrides: Partial<AiEvidenceProgress> = {}): AiEvidenceProgress {
  return {
    progress: 0.5,
    stage: 'Analyze',
    detail: 'working',
    done: false,
    failed: false,
    ...overrides,
  };
}

function createFakePorts(initialAnalysis: EditorAnalysisState = seedAnalysis()) {
  let analysis = initialAnalysis;
  let active: ActiveAiRequest | null = null;
  const ports: AiEvidencePorts = {
    analyze: vi.fn(async (): Promise<AiEvidenceResponse> => makeResponse()),
    cancelJob: vi.fn(async (): Promise<boolean> => true),
    readAnalysis: () => analysis,
    getActiveRequest: () => active,
    setActiveRequest: (request: ActiveAiRequest) => {
      active = request;
    },
    clearActiveRequest: (requestId: string) => {
      if (active?.requestId === requestId) {
        active = null;
      }
    },
    actions: {
      setAiPrompt: vi.fn((_fileId: string, _prompt: string): void => undefined),
      setAiJob: vi.fn((_fileId: string, _job: Partial<AiEvidenceJobState>): void => undefined),
      setAiResult: vi.fn((_fileId: string, _result: AiEvidenceResponse | null): void => undefined),
      setLprRuntimeStatus: vi.fn((_runtime: LprRuntimeStatus | null): void => undefined),
      replaceLprSession: vi.fn((_fileId: string, _session: LprSessionState): void => undefined),
    },
    notifyFeedback: vi.fn((_message: string | null): void => undefined),
    refreshRuntimeStatus: vi.fn(async (): Promise<void> => undefined),
    describeError: (error: unknown, fallback: string) => (
      error instanceof Error ? error.message : fallback
    ),
    logError: vi.fn((_message: string, _error: unknown): void => undefined),
    now: () => NOW,
    createRequestId: () => 'req-1',
    createHistoryId: () => 'hist-1',
  };
  return {
    ports,
    get active() {
      return active;
    },
    setActive(next: ActiveAiRequest | null) {
      active = next;
    },
    setAnalysis(next: EditorAnalysisState) {
      analysis = next;
    },
  };
}

function lastSetAiJobArg(ports: AiEvidencePorts) {
  const calls = vi.mocked(ports.actions.setAiJob).mock.calls;
  return calls[calls.length - 1]?.[1];
}

describe('runAiEvidenceBegin', () => {
  it('opens a tracked request and resets prompt/result/job state', () => {
    const fake = createFakePorts();
    const result = runAiEvidenceBegin({ fileId: FILE_ID, prompt: '  find the plate  ' }, fake.ports);

    expect(result).toEqual({ ok: true, data: { fileId: FILE_ID, requestId: 'req-1' } });
    expect(fake.active).toEqual({ requestId: 'req-1', fileId: FILE_ID });
    expect(fake.ports.actions.setAiPrompt).toHaveBeenCalledWith(FILE_ID, 'find the plate');
    expect(fake.ports.actions.setAiResult).toHaveBeenCalledWith(FILE_ID, null);
    expect(fake.ports.actions.setAiJob).toHaveBeenCalledWith(FILE_ID, expect.objectContaining({
      status: 'running',
      progress: 0.05,
      stage: 'Prepare',
      requestId: 'req-1',
      error: null,
      startedAt: NOW,
      updatedAt: NOW,
      stageStartedAt: NOW,
    }));
    expect(fake.ports.notifyFeedback).toHaveBeenCalledWith(null);
  });

  it('rejects a blank prompt with feedback and no side effects', () => {
    const fake = createFakePorts();
    const result = runAiEvidenceBegin({ fileId: FILE_ID, prompt: '   ' }, fake.ports);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toContain('natural-language description');
    }
    expect(fake.ports.notifyFeedback).toHaveBeenCalledWith(
      'AI evidence analysis requires a natural-language description.',
    );
    expect(fake.ports.actions.setAiPrompt).not.toHaveBeenCalled();
    expect(fake.ports.actions.setAiJob).not.toHaveBeenCalled();
    expect(fake.active).toBeNull();
  });
});

describe('runAiEvidenceJobUpdate', () => {
  it('preserves the stage clock when the stage is unchanged', () => {
    const fake = createFakePorts(seedAnalysis({
      aiJob: {
        ...DEFAULT_AI_EVIDENCE_JOB_STATE,
        status: 'running',
        stage: 'Prepare',
        requestId: 'req-1',
        startedAt: 't0',
        stageStartedAt: 't-stage',
        updatedAt: 't0',
      },
    }));

    const result = runAiEvidenceJobUpdate(
      { fileId: FILE_ID, job: { stage: 'Prepare', detail: 'still preparing' } },
      fake.ports,
    );

    expect(result).toEqual({ ok: true, data: { fileId: FILE_ID } });
    expect(lastSetAiJobArg(fake.ports)).toMatchObject({
      stageStartedAt: 't-stage',
      updatedAt: NOW,
    });
  });

  it('resets the stage clock when the stage changes', () => {
    const fake = createFakePorts(seedAnalysis({
      aiJob: {
        ...DEFAULT_AI_EVIDENCE_JOB_STATE,
        status: 'running',
        stage: 'Prepare',
        requestId: 'req-1',
        startedAt: 't0',
        stageStartedAt: 't-stage',
        updatedAt: 't0',
      },
    }));

    runAiEvidenceJobUpdate({ fileId: FILE_ID, job: { stage: 'Analyze' } }, fake.ports);

    expect(lastSetAiJobArg(fake.ports)).toMatchObject({
      stage: 'Analyze',
      stageStartedAt: NOW,
      updatedAt: NOW,
    });
  });
});

describe('runAiEvidenceProgress', () => {
  it('maps a progress event onto the active job with clamped progress', () => {
    const fake = createFakePorts();
    fake.setActive({ requestId: 'req-1', fileId: FILE_ID });

    const result = runAiEvidenceProgress(
      { fileId: FILE_ID, requestId: 'req-1', progress: makeProgress({ progress: 9 }) },
      fake.ports,
    );

    expect(result).toEqual({ ok: true, data: { applied: true } });
    expect(lastSetAiJobArg(fake.ports)).toMatchObject({
      status: 'running',
      progress: 1,
      stage: 'Analyze',
      detail: 'working',
      requestId: 'req-1',
      error: null,
    });
  });

  it('maps a failed event to a failed job carrying the detail as error', () => {
    const fake = createFakePorts();
    fake.setActive({ requestId: 'req-1', fileId: FILE_ID });

    runAiEvidenceProgress(
      { fileId: FILE_ID, requestId: 'req-1', progress: makeProgress({ failed: true, detail: 'kaput' }) },
      fake.ports,
    );

    expect(lastSetAiJobArg(fake.ports)).toMatchObject({
      status: 'failed',
      error: 'kaput',
    });
  });

  it('ignores events for a superseded request without side effects', () => {
    const fake = createFakePorts();
    fake.setActive({ requestId: 'req-2', fileId: FILE_ID });

    const result = runAiEvidenceProgress(
      { fileId: FILE_ID, requestId: 'req-1', progress: makeProgress() },
      fake.ports,
    );

    expect(result).toEqual({ ok: true, data: { applied: false } });
    expect(fake.ports.actions.setAiJob).not.toHaveBeenCalled();
  });

  it('ignores events when no request is active', () => {
    const fake = createFakePorts();

    const result = runAiEvidenceProgress(
      { fileId: FILE_ID, requestId: 'req-1', progress: makeProgress({ done: true }) },
      fake.ports,
    );

    expect(result).toEqual({ ok: true, data: { applied: false } });
    expect(fake.ports.actions.setAiJob).not.toHaveBeenCalled();
  });
});

describe('runAiEvidenceProjection', () => {
  it('projects candidates into review mode with a history entry', () => {
    const candidate = makeCandidate('cand-1', 'ABC123');
    const track = makeTrack('t1', 500);
    const fake = createFakePorts();
    const response = makeResponse({
      requestId: 'req-1',
      primaryAnchor: makeFrameRef(500),
      projection: {
        interval: { startMs: 0, endMs: 1000 },
        targetTracks: [track],
        analysisTrack: track,
        selectedTargetTrackId: 't1',
        samples: [],
        candidates: [candidate],
        acceptedCandidateId: 'cand-1',
        review: null,
        provenance: null,
        decision: null,
      },
    });

    const result = runAiEvidenceProjection({ fileId: FILE_ID, response }, fake.ports);

    expect(result).toEqual({
      ok: true,
      data: { selectedTargetTrackId: 't1', acceptedCandidateId: 'cand-1', workflowMode: 'review' },
    });
    const calls = vi.mocked(fake.ports.actions.replaceLprSession).mock.calls;
    expect(calls).toHaveLength(1);
    const projected = calls[0]?.[1];
    expect(projected?.workflowMode).toBe('review');
    expect(projected?.selectedTargetTrackId).toBe('t1');
    expect(projected?.selectedTargetAnchor?.trackId).toBe('t1');
    expect(projected?.selectedTargetAnchor?.timeMs).toBe(500);
    expect(projected?.candidates).toHaveLength(1);
    expect(projected?.job).toMatchObject({ status: 'completed', stage: 'AI evidence', progress: 1 });
    expect(projected?.history).toHaveLength(1);
    expect(projected?.history[0]).toMatchObject({ id: 'hist-1', acceptedCandidateId: 'cand-1' });
  });

  it('falls back through the selection chain and stays in target mode without history', () => {
    const track = makeTrack('t9', 700);
    const fake = createFakePorts(seedAnalysis({
      lpr: buildDefaultLprState({ selectedTargetTrackId: 'current-track' }),
    }));
    const response = makeResponse({
      projection: {
        interval: null,
        targetTracks: [track],
        analysisTrack: null,
        selectedTargetTrackId: null,
        samples: [],
        candidates: [],
        acceptedCandidateId: null,
        review: null,
        provenance: null,
        decision: null,
      },
      targetSelection: makeSelection('t9'),
    });

    const result = runAiEvidenceProjection({ fileId: FILE_ID, response }, fake.ports);

    expect(result).toEqual({
      ok: true,
      data: { selectedTargetTrackId: 't9', acceptedCandidateId: null, workflowMode: 'target' },
    });
    const projected = vi.mocked(fake.ports.actions.replaceLprSession).mock.calls[0]?.[1];
    expect(projected?.workflowMode).toBe('target');
    expect(projected?.history).toHaveLength(0);
  });
});

describe('runAiEvidenceComplete / runAiEvidenceFail', () => {
  it('lands the response, completes the job, and clears the active request', () => {
    const fake = createFakePorts();
    fake.setActive({ requestId: 'req-1', fileId: FILE_ID });
    const response = makeResponse();

    const result = runAiEvidenceComplete({ fileId: FILE_ID, requestId: 'req-1', response }, fake.ports);

    expect(result).toEqual({ ok: true, data: { applied: true } });
    expect(fake.ports.actions.setLprRuntimeStatus).toHaveBeenCalledWith(RUNTIME);
    expect(fake.ports.actions.setAiResult).toHaveBeenCalledWith(FILE_ID, response);
    expect(lastSetAiJobArg(fake.ports)).toMatchObject({
      status: 'completed',
      stage: 'Completed',
      detail: 'summary text',
      requestId: 'req-1',
    });
    expect(fake.ports.actions.replaceLprSession).toHaveBeenCalledTimes(1);
    expect(fake.active).toBeNull();
  });

  it('ignores a stale completion without side effects', () => {
    const fake = createFakePorts();
    fake.setActive({ requestId: 'req-2', fileId: FILE_ID });

    const result = runAiEvidenceComplete(
      { fileId: FILE_ID, requestId: 'req-1', response: makeResponse() },
      fake.ports,
    );

    expect(result).toEqual({ ok: true, data: { applied: false } });
    expect(fake.ports.actions.setAiResult).not.toHaveBeenCalled();
    expect(fake.ports.actions.replaceLprSession).not.toHaveBeenCalled();
    expect(fake.active).toEqual({ requestId: 'req-2', fileId: FILE_ID });
  });

  it('records a failure with feedback and clears the active request', () => {
    const fake = createFakePorts();
    fake.setActive({ requestId: 'req-1', fileId: FILE_ID });

    const result = runAiEvidenceFail(
      { fileId: FILE_ID, requestId: 'req-1', error: new Error('boom') },
      fake.ports,
    );

    expect(result).toEqual({ ok: true, data: { applied: true, error: 'boom' } });
    expect(fake.ports.logError).toHaveBeenCalledWith('AI evidence analysis failed.', expect.any(Error));
    expect(lastSetAiJobArg(fake.ports)).toMatchObject({
      status: 'failed',
      stage: 'Failed',
      error: 'boom',
      requestId: 'req-1',
    });
    expect(fake.ports.notifyFeedback).toHaveBeenCalledWith('boom');
    expect(fake.active).toBeNull();
  });

  it('ignores a stale failure without side effects', () => {
    const fake = createFakePorts();

    const result = runAiEvidenceFail(
      { fileId: FILE_ID, requestId: 'req-1', error: new Error('boom') },
      fake.ports,
    );

    expect(result).toEqual({ ok: true, data: { applied: false, error: null } });
    expect(fake.ports.actions.setAiJob).not.toHaveBeenCalled();
    expect(fake.ports.notifyFeedback).not.toHaveBeenCalled();
  });
});

describe('runAiEvidenceAnalysis', () => {
  const baseInput = {
    fileId: FILE_ID,
    sourcePath: '/media/clip.mp4',
    assetReady: true,
    prompt: 'find the plate',
    markerRect: null,
    compressionMode: 'standard' as const,
  };

  it('runs the full success path and maps the request from the LPR session', async () => {
    const fake = createFakePorts(seedAnalysis({
      lpr: buildDefaultLprState({ countryHints: ['US'] }),
    }));

    const result = await runAiEvidenceAnalysis(baseInput, fake.ports);

    expect(result).toEqual({
      ok: true,
      data: { fileId: FILE_ID, requestId: 'req-1', applied: true },
    });
    expect(fake.ports.analyze).toHaveBeenCalledTimes(1);
    expect(fake.ports.analyze).toHaveBeenCalledWith(expect.objectContaining({
      sourcePath: '/media/clip.mp4',
      description: 'find the plate',
      countryHints: ['US'],
      targetVehicleKind: 'any',
      requestId: 'req-1',
    }));
    expect(fake.ports.actions.setAiResult).toHaveBeenCalledWith(FILE_ID, expect.objectContaining({
      summary: 'summary text',
    }));
    expect(fake.ports.actions.replaceLprSession).toHaveBeenCalledTimes(1);
    expect(fake.active).toBeNull();
  });

  it('records the failure and returns an error when analysis throws', async () => {
    const fake = createFakePorts();
    vi.mocked(fake.ports.analyze).mockRejectedValue(new Error('engine down'));

    const result = await runAiEvidenceAnalysis(baseInput, fake.ports);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe('engine down');
    }
    expect(lastSetAiJobArg(fake.ports)).toMatchObject({ status: 'failed', error: 'engine down' });
    expect(fake.ports.notifyFeedback).toHaveBeenCalledWith('engine down');
    expect(fake.ports.actions.setAiResult).toHaveBeenCalledWith(FILE_ID, null);
    expect(fake.active).toBeNull();
  });

  it('rejects a missing asset without calling the infrastructure', async () => {
    const fake = createFakePorts();

    const result = await runAiEvidenceAnalysis({ ...baseInput, assetReady: false }, fake.ports);

    expect(result.ok).toBe(false);
    expect(fake.ports.analyze).not.toHaveBeenCalled();
    expect(fake.ports.actions.setAiPrompt).not.toHaveBeenCalled();
  });

  it('rejects a blank prompt with feedback and no analysis call', async () => {
    const fake = createFakePorts();

    const result = await runAiEvidenceAnalysis({ ...baseInput, prompt: '  ' }, fake.ports);

    expect(result.ok).toBe(false);
    expect(fake.ports.notifyFeedback).toHaveBeenCalledWith(
      'AI evidence analysis requires a natural-language description.',
    );
    expect(fake.ports.analyze).not.toHaveBeenCalled();
  });

  it('reports a superseded run as not applied', async () => {
    const fake = createFakePorts();
    vi.mocked(fake.ports.analyze).mockImplementation(async () => {
      fake.setActive({ requestId: 'req-2', fileId: FILE_ID });
      return makeResponse();
    });

    const result = await runAiEvidenceAnalysis(baseInput, fake.ports);

    expect(result).toEqual({
      ok: true,
      data: { fileId: FILE_ID, requestId: 'req-1', applied: false },
    });
    expect(fake.ports.actions.setAiResult).toHaveBeenCalledWith(FILE_ID, null);
    expect(fake.ports.actions.replaceLprSession).not.toHaveBeenCalled();
  });
});

describe('runAiEvidenceCancel', () => {
  it('is a no-op without an active request', async () => {
    const fake = createFakePorts();

    const result = await runAiEvidenceCancel({}, fake.ports);

    expect(result).toEqual({ ok: true, data: { cancelled: false } });
    expect(fake.ports.cancelJob).not.toHaveBeenCalled();
    expect(fake.ports.actions.setAiJob).not.toHaveBeenCalled();
  });

  it('cancels the active request and refreshes the runtime status', async () => {
    const fake = createFakePorts(seedAnalysis({
      aiJob: {
        ...DEFAULT_AI_EVIDENCE_JOB_STATE,
        status: 'running',
        stage: 'Analyze',
        requestId: 'req-1',
      },
    }));
    fake.setActive({ requestId: 'req-1', fileId: FILE_ID });

    const result = await runAiEvidenceCancel({}, fake.ports);

    expect(result).toEqual({ ok: true, data: { cancelled: true } });
    expect(fake.ports.cancelJob).toHaveBeenCalledTimes(1);
    const jobCalls = vi.mocked(fake.ports.actions.setAiJob).mock.calls;
    expect(jobCalls).toHaveLength(2);
    expect(jobCalls[0]?.[1]).toMatchObject({
      status: 'cancelled',
      stage: 'Analyze',
      detail: 'Cancelling current AI evidence task.',
    });
    expect(jobCalls[1]?.[1]).toMatchObject({
      status: 'cancelled',
      progress: 1,
      detail: 'Current AI evidence task cancelled.',
    });
    expect(fake.ports.refreshRuntimeStatus).toHaveBeenCalledTimes(1);
    expect(fake.active).toBeNull();
  });

  it('records a failed cancellation with feedback and returns an error', async () => {
    const fake = createFakePorts();
    fake.setActive({ requestId: 'req-1', fileId: FILE_ID });
    vi.mocked(fake.ports.cancelJob).mockRejectedValue(new Error('cannot cancel'));

    const result = await runAiEvidenceCancel({}, fake.ports);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe('cannot cancel');
    }
    expect(lastSetAiJobArg(fake.ports)).toMatchObject({
      status: 'failed',
      detail: 'Unable to cancel the current AI evidence task.',
      error: 'cannot cancel',
    });
    expect(fake.ports.notifyFeedback).toHaveBeenCalledWith('cannot cancel');
    expect(fake.ports.refreshRuntimeStatus).not.toHaveBeenCalled();
  });
});
