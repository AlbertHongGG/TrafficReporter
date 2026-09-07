/**
 * LPR use-case tests (Phase 4-A).
 *
 * Every `runX(input, ports)` use-case is driven with fake ports: happy path,
 * error path (IpcCommandError command/transport semantics), and
 * cancel/concurrency (stale-completion) semantics.
 */
import { describe, expect, it } from 'vitest'

import { IpcCommandError } from '../../../../platform/ipc/ipc-unwrap'
import { getErrorSummary } from '../../../../utils/logger'
import { buildDefaultLprState } from '../../domain/lprState'
import type {
  EditorFileState,
  LprJobState,
  TimelineClip,
  TimelineIntervalSelection,
  VideoMarkerRect,
} from '../../domain/model'
import type {
  LprEvidenceExportResponse,
  LprFrameAnalysisResponse,
  LprIntervalAnalysisResponse,
  LprPlateCandidate,
  LprRuntimeStatus,
  LprSessionState,
  LprTargetScanResponse,
  LprTargetTrack,
  LprTrackedRegion,
} from '../../domain/lprState'
import {
  commitLprJobUpdate,
  type LprPorts,
  type LprStoreActions,
} from './lprPorts.usecase'
import { runLprScanTargets } from './lprScanTargets.usecase'
import { runLprAnalyzeFrame } from './lprAnalyzeFrame.usecase'
import { runLprAnalyzeInterval } from './lprAnalyzeInterval.usecase'
import { runLprRefreshRuntimeStatus } from './lprRuntimeStatus.usecase'
import { runLprCancelJob } from './lprCancelJob.usecase'
import { runLprSelectTargetTrack } from './lprTargetSelection.usecase'
import { runLprApplyCountryHints } from './lprCountryHints.usecase'
import {
  runLprSetIntervalBoundary,
  runLprUseClipInterval,
  suggestLprInterval,
} from './lprIntervalEditing.usecase'
import {
  resolveLprEvidenceOutputPath,
  runLprExportEvidence,
} from './lprExportEvidence.usecase'
import { runLprApplyProgressEvent } from './lprProgressEvent.usecase'

const BOX: VideoMarkerRect = { x: 0.1, y: 0.1, width: 0.3, height: 0.2 }

function makeRuntime(overrides: Partial<LprRuntimeStatus> = {}): LprRuntimeStatus {
  return {
    available: true,
    pythonExecutable: '/usr/bin/python3',
    runtimeScript: 'lpr.py',
    version: '1.0.0',
    missingPackages: [],
    installedPackages: ['ultralytics'],
    detail: 'ready',
    ...overrides,
  }
}

function makeCandidate(id: string, text: string): LprPlateCandidate {
  return {
    id,
    text,
    confidence: 0.92,
    source: 'fusion',
    frameTimeMs: 1500,
    countryCode: null,
    box: null,
    quality: null,
  }
}

function makeDetection(id: string, timeMs: number): LprTrackedRegion {
  return { id, timeMs, box: { ...BOX }, confidence: 0.8, className: 'car' }
}

function makeTrack(id: string, times: number[]): LprTargetTrack {
  return {
    id,
    className: 'car',
    label: 'car 1',
    confidence: 0.8,
    frames: times.map((timeMs, index) => makeDetection(`${id}-f${index}`, timeMs)),
  }
}

function makeClip(overrides: Partial<TimelineClip> = {}): TimelineClip {
  return {
    id: 'clip-1',
    assetId: 'asset-1',
    trackId: 'track-1',
    startMs: 1000,
    inPointMs: 0,
    outPointMs: 2000,
    muted: false,
    ...overrides,
  }
}

function makeFile(overrides: Partial<EditorFileState> = {}): EditorFileState {
  return {
    id: 'file-1',
    asset: {
      id: 'asset-1',
      name: 'cam.mp4',
      path: '/tmp/cam.mp4',
      status: 'ready',
      url: null,
      thumbnailUrl: null,
      hasVideo: true,
      hasAudio: false,
      durationMs: 60000,
      fps: 30,
      audioBitrateKbps: null,
      width: 1920,
      height: 1080,
      kind: 'video',
    },
    track: { id: 'track-1', name: 'V1', order: 0 },
    clips: [],
    renderProfile: { format: 'mp4', fps: 30, compressionMode: 'standard' },
    selectedClipIds: [],
    playheadMs: 1500,
    zoom: 100,
    previewVolume: 1,
    previewMuted: false,
    isPlaying: false,
    markerRect: null,
    ...overrides,
  }
}

interface ActionCall {
  name: string
  args: unknown[]
}

interface FakeInfra {
  scanTargets: LprPorts['scanTargets']
  analyzeFrame: LprPorts['analyzeFrame']
  analyzeInterval: LprPorts['analyzeInterval']
  exportEvidence: LprPorts['exportEvidence']
  getRuntimeStatus: LprPorts['getRuntimeStatus']
  cancelRuntimeJob: LprPorts['cancelRuntimeJob']
}

interface FakeMutableState {
  file: EditorFileState | null
  session: LprSessionState
  isPlaying: boolean
  activeRequestId: string | null
  cancelled: Set<string>
  counter: number
}

interface FakePortsBundle {
  ports: LprPorts
  calls: ActionCall[]
  feedbacks: (string | null)[]
  logged: { message: string; error: unknown }[]
  infraCalls: string[]
  state: FakeMutableState
  infra: FakeInfra
}

function defaultScanResponse(): LprTargetScanResponse {
  return { detections: [makeDetection('det-1', 1500)], runtime: makeRuntime() }
}

function defaultFrameResponse(): LprFrameAnalysisResponse {
  return {
    detections: [makeDetection('det-1', 1500)],
    sample: { id: 'sample-1', timeMs: 1500, candidates: [] },
    candidates: [makeCandidate('cand-1', 'ABC-123')],
    acceptedCandidateId: 'cand-1',
    review: { status: 'accepted', acceptedCandidateId: 'cand-1', suggestedCandidateId: 'cand-1', reasons: [] },
    provenance: {
      requestId: null,
      command: 'analyze_lpr_frame',
      analysisProfileId: null,
      developerDiagnosticsEnabled: false,
      runtimeVersion: null,
      emittedAtMs: 0,
    },
    decision: null,
    runtime: makeRuntime(),
    jobStatus: 'completed',
  }
}

function defaultIntervalResponse(): LprIntervalAnalysisResponse {
  return {
    targetTracks: [makeTrack('track-1', [500, 900])],
    analysisTrack: makeTrack('track-1', [500, 900]),
    samples: [],
    candidates: [makeCandidate('cand-1', 'ABC-123')],
    acceptedCandidateId: 'cand-1',
    review: { status: 'accepted', acceptedCandidateId: 'cand-1', suggestedCandidateId: 'cand-1', reasons: [] },
    provenance: {
      requestId: null,
      command: 'analyze_lpr_interval',
      analysisProfileId: null,
      developerDiagnosticsEnabled: false,
      runtimeVersion: null,
      emittedAtMs: 0,
    },
    decision: null,
    summary: 'interval done',
    runtime: makeRuntime(),
    jobStatus: 'completed',
    tracking: null,
    sequence: null,
  }
}

function createFakePorts(): FakePortsBundle {
  const calls: ActionCall[] = []
  const feedbacks: (string | null)[] = []
  const logged: { message: string; error: unknown }[] = []
  const infraCalls: string[] = []
  const state: FakeMutableState = {
    file: makeFile(),
    session: buildDefaultLprState(),
    isPlaying: false,
    activeRequestId: null as string | null,
    cancelled: new Set<string>(),
    counter: 0,
  }

  const record = (name: string, ...args: unknown[]): void => {
    calls.push({ name, args })
  }

  const actions: LprStoreActions = {
    setLprRuntimeStatus: (runtimeStatus) => record('setLprRuntimeStatus', runtimeStatus),
    setLprJob: (job) => record('setLprJob', job),
    setLprTargetTracks: (targetTracks) => record('setLprTargetTracks', targetTracks),
    setLprAnalysisTrack: (analysisTrack) => record('setLprAnalysisTrack', analysisTrack),
    setLprMode: (workflowMode) => record('setLprMode', workflowMode),
    setLprInterval: (interval) => record('setLprInterval', interval),
    setLprCountryHints: (countryHints) => record('setLprCountryHints', countryHints),
    selectLprTargetTrack: (targetTrackId, anchor) => record('selectLprTargetTrack', targetTrackId, anchor),
    setLprSamples: (samples) => record('setLprSamples', samples),
    setLprCandidates: (candidates) => record('setLprCandidates', candidates),
    setLprReview: (review) => record('setLprReview', review),
    setLprProvenance: (provenance) => record('setLprProvenance', provenance),
    setLprDecision: (decision) => record('setLprDecision', decision),
    appendLprHistory: (entry) => record('appendLprHistory', entry),
    setPlayhead: (playheadMs) => record('setPlayhead', playheadMs),
    setPlaying: (isPlaying) => record('setPlaying', isPlaying),
  }

  const infra: FakeInfra = {
    scanTargets: async (request) => {
      infraCalls.push('scanTargets')
      void request
      return defaultScanResponse()
    },
    analyzeFrame: async (request) => {
      infraCalls.push('analyzeFrame')
      void request
      return defaultFrameResponse()
    },
    analyzeInterval: async (request) => {
      infraCalls.push('analyzeInterval')
      void request
      return defaultIntervalResponse()
    },
    exportEvidence: async (request): Promise<LprEvidenceExportResponse> => {
      infraCalls.push('exportEvidence')
      void request
      return {
        jsonPath: '/tmp/evidence.json',
        imagePath: '/tmp/evidence.png',
        bundleDir: '/tmp/evidence-bundle',
        exportedFileCount: 3,
        decisionFrameCount: 2,
      }
    },
    getRuntimeStatus: async () => {
      infraCalls.push('getRuntimeStatus')
      return makeRuntime()
    },
    cancelRuntimeJob: async () => {
      infraCalls.push('cancelRuntimeJob')
      return true
    },
  }

  const ports: LprPorts = {
    scanTargets: (request) => infra.scanTargets(request),
    analyzeFrame: (request) => infra.analyzeFrame(request),
    analyzeInterval: (request) => infra.analyzeInterval(request),
    exportEvidence: (request) => infra.exportEvidence(request),
    getRuntimeStatus: () => infra.getRuntimeStatus(),
    cancelRuntimeJob: () => infra.cancelRuntimeJob(),
    readActiveFile: () => state.file,
    readLprSession: () => state.session,
    readIsPlaying: () => state.isPlaying,
    getActiveRequestId: () => state.activeRequestId,
    beginRequest: (stage, detail, progress) => {
      state.counter += 1
      const requestId = `req-${state.counter}`
      state.activeRequestId = requestId
      state.cancelled.delete(requestId)
      commitLprJobUpdate(ports, {
        status: 'running',
        requestId,
        progress,
        stage,
        detail,
        error: null,
        reasonCode: null,
        startedAt: '2026-01-01T00:00:00.000Z',
        trackingTier: null,
        coverageRatio: null,
      })
      return requestId
    },
    isStale: (requestId) => state.activeRequestId !== requestId || state.cancelled.has(requestId),
    markCancelled: (requestId) => {
      state.cancelled.add(requestId)
    },
    isCancelled: (requestId) => state.cancelled.has(requestId),
    unmarkCancelled: (requestId) => {
      state.cancelled.delete(requestId)
    },
    clearActiveRequest: (requestId) => {
      if (state.activeRequestId === requestId) {
        state.activeRequestId = null
      }
    },
    forgetRequest: (requestId) => {
      if (state.activeRequestId === requestId) {
        state.activeRequestId = null
      }
      state.cancelled.delete(requestId)
    },
    actions,
    notifyFeedback: (message) => {
      feedbacks.push(message)
    },
    describeError: (error, fallback) => getErrorSummary(error, fallback),
    logError: (message, error) => {
      logged.push({ message, error })
    },
    now: () => '2026-01-01T00:00:00.000Z',
    createRequestId: () => {
      state.counter += 1
      return `req-${state.counter}`
    },
    createHistoryId: () => 'lpr-history-test-1',
    overlayToleranceMs: 360,
  }

  return { ports, calls, feedbacks, logged, infraCalls, state, infra }
}

function jobPatches(calls: ActionCall[]): Partial<LprJobState>[] {
  return calls
    .filter((call) => call.name === 'setLprJob')
    .map((call) => call.args[0] as Partial<LprJobState>)
}

function lastJobPatch(calls: ActionCall[]): Partial<LprJobState> {
  const patches = jobPatches(calls)
  const last = patches[patches.length - 1]
  if (!last) {
    throw new Error('expected at least one setLprJob dispatch')
  }
  return last
}

describe('lprScanTargets use-case', () => {
  it('dispatches tracks + mode + completed job on the happy path', async () => {
    const fake = createFakePorts()
    const result = await runLprScanTargets({ playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.detectionCount).toBe(1)
    expect(result.data.workflowMode).toBe('target')
    const names = fake.calls.map((call) => call.name)
    expect(names).toContain('setLprTargetTracks')
    expect(names).toContain('setLprMode')
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'completed', stage: 'Targets' })
    expect(fake.state.activeRequestId).toBeNull()
  })

  it('falls back to range mode with an empty detection list', async () => {
    const fake = createFakePorts()
    fake.infra.scanTargets = async () => ({ detections: [], runtime: makeRuntime() })
    const result = await runLprScanTargets({ playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.workflowMode).toBe('range')
    expect(lastJobPatch(fake.calls)).toMatchObject({ detail: 'No target found in the current frame.' })
  })

  it('skips silently without infra when no ready file exists', async () => {
    const fake = createFakePorts()
    fake.state.file = null
    const result = await runLprScanTargets({ playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('skipped')
    expect(fake.infraCalls).not.toContain('scanTargets')
    expect(fake.calls).toHaveLength(0)
  })

  it('maps a backend command failure to failed job + feedback + command error', async () => {
    const fake = createFakePorts()
    fake.infra.scanTargets = async () => {
      throw new IpcCommandError('command', 'scan_lpr_targets', 'python exploded')
    }
    const result = await runLprScanTargets({ playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('command')
    expect(result.error.command).toBe('scan_lpr_targets')
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'failed', stage: 'Targets' })
    expect(fake.feedbacks).toContain('[scan_lpr_targets] python exploded')
  })

  it('ignores a stale completion without dispatching results', async () => {
    const fake = createFakePorts()
    fake.infra.scanTargets = async () => {
      const active = fake.ports.getActiveRequestId()
      if (active) {
        fake.ports.markCancelled(active)
      }
      return defaultScanResponse()
    }
    const result = await runLprScanTargets({ playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('stale')
    expect(fake.calls.map((call) => call.name)).not.toContain('setLprTargetTracks')
    expect(fake.feedbacks).toHaveLength(0)
  })
})

describe('lprAnalyzeFrame use-case', () => {
  it('stores samples/candidates/history and completes the job', async () => {
    const fake = createFakePorts()
    const result = await runLprAnalyzeFrame({ playheadMs: 1500, countryHintDraft: 'TW, US' }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.candidateCount).toBe(1)
    expect(result.data.detail).toBe('Accepted ABC-123')
    const names = fake.calls.map((call) => call.name)
    expect(names).toContain('setLprCountryHints')
    expect(names).toContain('setLprSamples')
    expect(names).toContain('setLprCandidates')
    expect(names).toContain('appendLprHistory')
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'completed', stage: 'Frame' })
  })

  it('resolves the selected target box from the session track', async () => {
    const fake = createFakePorts()
    fake.state.session = buildDefaultLprState({
      targetTracks: [makeTrack('track-1', [1400, 1600])],
      selectedTargetTrackId: 'track-1',
    })
    let seenBox: unknown = 'unset'
    fake.infra.analyzeFrame = async (request) => {
      seenBox = request.selectedTargetBox
      return defaultFrameResponse()
    }
    await runLprAnalyzeFrame({ playheadMs: 1500, countryHintDraft: null }, fake.ports)
    expect(seenBox).toMatchObject({ x: 0.1, y: 0.1 })
  })

  it('maps a transport failure with the frame reason code', async () => {
    const fake = createFakePorts()
    fake.infra.analyzeFrame = async () => {
      throw new Error('ipc bridge down')
    }
    const result = await runLprAnalyzeFrame({ playheadMs: 1500, countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('transport')
    expect(result.error.reasonCode).toBe('frame-analysis-failed')
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'failed', reasonCode: 'frame-analysis-failed' })
    expect(fake.feedbacks).toContain('ipc bridge down')
  })

  it('ignores a stale frame completion silently', async () => {
    const fake = createFakePorts()
    fake.infra.analyzeFrame = async () => {
      const active = fake.ports.getActiveRequestId()
      if (active) {
        fake.ports.markCancelled(active)
      }
      return defaultFrameResponse()
    }
    const result = await runLprAnalyzeFrame({ playheadMs: 1500, countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('stale')
    expect(fake.calls.map((call) => call.name)).not.toContain('setLprCandidates')
  })
})

describe('lprAnalyzeInterval use-case', () => {
  function readyIntervalSession(): LprSessionState {
    return buildDefaultLprState({
      interval: { startMs: 0, endMs: 2000 },
      targetTracks: [makeTrack('track-1', [500, 900])],
      selectedTargetTrackId: 'track-1',
      selectedTargetAnchor: { trackId: 'track-1', className: 'car', timeMs: 500, box: { ...BOX } },
    })
  }

  it('rejects a missing interval with failed job + feedback', async () => {
    const fake = createFakePorts()
    const result = await runLprAnalyzeInterval({ countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('validation')
    expect(lastJobPatch(fake.calls)).toMatchObject({
      status: 'failed',
      detail: 'Range analysis requires an explicit interval.',
    })
    expect(fake.feedbacks).toContain('Set Clip, In, or Out before running Range.')
    expect(fake.infraCalls).not.toContain('analyzeInterval')
  })

  it('rejects a missing target selection', async () => {
    const fake = createFakePorts()
    fake.state.session = buildDefaultLprState({ interval: { startMs: 0, endMs: 2000 } })
    const result = await runLprAnalyzeInterval({ countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(fake.feedbacks).toContain('Select a target before running Range.')
  })

  it('rejects an anchor outside the interval', async () => {
    const fake = createFakePorts()
    fake.state.session = buildDefaultLprState({
      interval: { startMs: 0, endMs: 1000 },
      targetTracks: [makeTrack('track-1', [500])],
      selectedTargetTrackId: 'track-1',
      selectedTargetAnchor: { trackId: 'track-1', className: 'car', timeMs: 5000, box: { ...BOX } },
    })
    const result = await runLprAnalyzeInterval({ countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('validation')
    expect(fake.infraCalls).not.toContain('analyzeInterval')
  })

  it('completes the happy path and switches to review mode', async () => {
    const fake = createFakePorts()
    fake.state.session = readyIntervalSession()
    const result = await runLprAnalyzeInterval({ countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.candidateCount).toBe(1)
    const names = fake.calls.map((call) => call.name)
    expect(names).toContain('setLprAnalysisTrack')
    expect(names).toContain('setLprMode')
    expect(names).toContain('appendLprHistory')
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'completed', stage: 'Interval' })
  })

  it('surfaces degraded job status with the backend summary', async () => {
    const fake = createFakePorts()
    fake.state.session = readyIntervalSession()
    fake.infra.analyzeInterval = async () => ({
      ...defaultIntervalResponse(),
      jobStatus: 'degraded',
      summary: 'Coverage 60% (detection-fallback).',
      tracking: {
        trackingTier: 'detection-fallback',
        anchorStatus: 'degraded',
        coverageRatio: 0.6,
        trackedFrameCount: 6,
        requestedFrameCount: 10,
        degradedReason: 'coverage-gap',
        terminatedEarly: false,
      },
    })
    const result = await runLprAnalyzeInterval({ countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.detail).toBe('Coverage 60% (detection-fallback).')
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'degraded', reasonCode: 'coverage-gap' })
  })

  it('maps an interval backend failure with the interval reason code', async () => {
    const fake = createFakePorts()
    fake.state.session = readyIntervalSession()
    fake.infra.analyzeInterval = async () => {
      throw new IpcCommandError('command', 'analyze_lpr_interval', 'range blew up')
    }
    const result = await runLprAnalyzeInterval({ countryHintDraft: null }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('command')
    expect(result.error.reasonCode).toBe('interval-analysis-failed')
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'failed', reasonCode: 'interval-analysis-failed' })
  })
})

describe('lprRuntimeStatus use-case', () => {
  it('stores the inspected runtime on success', async () => {
    const fake = createFakePorts()
    const result = await runLprRefreshRuntimeStatus(fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.available).toBe(true)
    expect(fake.calls.map((call) => call.name)).toContain('setLprRuntimeStatus')
  })

  it('stores an unavailable fallback instead of throwing', async () => {
    const fake = createFakePorts()
    fake.infra.getRuntimeStatus = async () => {
      throw new Error('no python')
    }
    const result = await runLprRefreshRuntimeStatus(fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.available).toBe(false)
    expect(result.data.detail).toBe('no python')
  })
})

describe('lprCancelJob use-case', () => {
  it('is a no-op without an active request', async () => {
    const fake = createFakePorts()
    const result = await runLprCancelJob(fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.cancelled).toBe(false)
    expect(fake.infraCalls).not.toContain('cancelRuntimeJob')
  })

  it('cancels the active request and reconciles the job', async () => {
    const fake = createFakePorts()
    const requestId = fake.ports.beginRequest('Frame', 'Analyzing.', 0.24)
    const result = await runLprCancelJob(fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data).toEqual({ requestId, cancelled: true })
    expect(fake.infraCalls).toContain('cancelRuntimeJob')
    expect(fake.state.activeRequestId).toBeNull()
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'cancelled', detail: 'Current LPR task cancelled.' })
  })

  it('unmarks the request and fails the job when cancel itself fails', async () => {
    const fake = createFakePorts()
    const requestId = fake.ports.beginRequest('Frame', 'Analyzing.', 0.24)
    fake.infra.cancelRuntimeJob = async () => {
      throw new IpcCommandError('transport', 'cancel_lpr_runtime_job', 'bridge gone')
    }
    const result = await runLprCancelJob(fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.reasonCode).toBe('cancel-failed')
    expect(fake.state.activeRequestId).toBe(requestId)
    expect(fake.ports.isCancelled(requestId)).toBe(false)
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'failed', reasonCode: 'cancel-failed' })
    expect(fake.feedbacks).toContain('[cancel_lpr_runtime_job] bridge gone')
  })
})

describe('lprTargetSelection use-case', () => {
  it('anchors, selects, seeks, and pauses playback', () => {
    const fake = createFakePorts()
    fake.state.session = buildDefaultLprState({ targetTracks: [makeTrack('track-1', [1400, 1600])] })
    fake.state.isPlaying = true
    const result = runLprSelectTargetTrack({ targetTrackId: 'track-1', playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.anchor?.trackId).toBe('track-1')
    expect(result.data.playheadMs).toBe(1500)
    expect(result.data.wasPlaying).toBe(true)
    const names = fake.calls.map((call) => call.name)
    expect(names).toContain('selectLprTargetTrack')
    expect(names).toContain('setPlayhead')
    expect(names).toContain('setPlaying')
  })

  it('leaves playback untouched when already paused', () => {
    const fake = createFakePorts()
    fake.state.session = buildDefaultLprState({ targetTracks: [makeTrack('track-1', [1400])] })
    const result = runLprSelectTargetTrack({ targetTrackId: 'track-1', playheadMs: 1400 }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.wasPlaying).toBe(false)
    expect(fake.calls.map((call) => call.name)).not.toContain('setPlaying')
  })
})

describe('lprCountryHints use-case', () => {
  it('parses and stores comma-separated hints', () => {
    const fake = createFakePorts()
    const result = runLprApplyCountryHints({ draft: ' TW, us ,,jp ' }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.countryHints).toEqual(['TW', 'us', 'jp'])
    expect(fake.calls.map((call) => call.name)).toContain('setLprCountryHints')
  })

  it('normalizes the stored session hints when the draft is null', () => {
    const fake = createFakePorts()
    fake.state.session = buildDefaultLprState({ countryHints: ['TW'] })
    const result = runLprApplyCountryHints({ draft: null }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.countryHints).toEqual(['TW'])
  })
})

describe('lprIntervalEditing use-cases', () => {
  it('prefers the explicit session interval when suggesting', () => {
    const fake = createFakePorts()
    const interval: TimelineIntervalSelection = { startMs: 100, endMs: 900 }
    fake.state.session = buildDefaultLprState({ interval })
    expect(suggestLprInterval({ playheadMs: 5000 }, fake.ports)).toEqual(interval)
  })

  it('falls back to the selected clip range', () => {
    const fake = createFakePorts()
    fake.state.file = makeFile({ clips: [makeClip()], selectedClipIds: ['clip-1'] })
    expect(suggestLprInterval({ playheadMs: 5000 }, fake.ports)).toEqual({ startMs: 1000, endMs: 3000 })
  })

  it('falls back to ±1s around the playhead without clips', () => {
    const fake = createFakePorts()
    expect(suggestLprInterval({ playheadMs: 5000 }, fake.ports)).toEqual({ startMs: 4000, endMs: 6000 })
  })

  it('sets the start boundary from the playhead', () => {
    const fake = createFakePorts()
    fake.state.session = buildDefaultLprState({ interval: { startMs: 0, endMs: 2000 } })
    const result = runLprSetIntervalBoundary({ boundary: 'start', playheadMs: 400 }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data).toEqual({ startMs: 400, endMs: 2000 })
    expect(fake.calls.map((call) => call.name)).toContain('setLprInterval')
  })

  it('adopts the clip interval and skips when no clip exists', () => {
    const withClip = createFakePorts()
    withClip.state.file = makeFile({ clips: [makeClip()], selectedClipIds: ['clip-1'] })
    const adopted = runLprUseClipInterval({ playheadMs: 1500 }, withClip.ports)
    expect(adopted.ok).toBe(true)
    if (!adopted.ok) {
      return
    }
    expect(adopted.data).toEqual({ startMs: 1000, endMs: 3000 })

    const withoutClip = createFakePorts()
    const skipped = runLprUseClipInterval({ playheadMs: 1500 }, withoutClip.ports)
    expect(skipped.ok).toBe(false)
    if (skipped.ok) {
      return
    }
    expect(skipped.error.kind).toBe('skipped')
  })
})

describe('lprExportEvidence use-case', () => {
  function readyExportSession(): LprSessionState {
    return buildDefaultLprState({
      candidates: [makeCandidate('cand-1', 'ABC-123')],
      samples: [{ id: 'sample-1', timeMs: 1500, candidates: [] }],
    })
  }

  it('normalizes the output path and reports the bundle summary', async () => {
    const fake = createFakePorts()
    fake.state.session = readyExportSession()
    let seenPath = ''
    fake.infra.exportEvidence = async (request) => {
      seenPath = request.outputPath
      return {
        jsonPath: '/tmp/e.json',
        imagePath: '/tmp/e.png',
        bundleDir: '/tmp/bundle',
        exportedFileCount: 3,
        decisionFrameCount: 2,
      }
    }
    const result = await runLprExportEvidence({ selectedPath: '/tmp/bundle', playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(true)
    expect(seenPath).toBe('/tmp/bundle.json')
    expect(fake.feedbacks[0]).toContain('/tmp/bundle')
  })

  it('keeps an explicit .json suffix untouched', () => {
    expect(resolveLprEvidenceOutputPath('/tmp/E.JSON')).toBe('/tmp/E.JSON')
    expect(resolveLprEvidenceOutputPath('/tmp/e')).toBe('/tmp/e.json')
  })

  it('skips when there is nothing to export', async () => {
    const fake = createFakePorts()
    const result = await runLprExportEvidence({ selectedPath: '/tmp/bundle', playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.kind).toBe('skipped')
    expect(fake.infraCalls).not.toContain('exportEvidence')
  })

  it('reports export failures through feedback', async () => {
    const fake = createFakePorts()
    fake.state.session = readyExportSession()
    fake.infra.exportEvidence = async () => {
      throw new IpcCommandError('command', 'export_lpr_evidence', 'disk full')
    }
    const result = await runLprExportEvidence({ selectedPath: '/tmp/bundle', playheadMs: 1500 }, fake.ports)

    expect(result.ok).toBe(false)
    if (result.ok) {
      return
    }
    expect(result.error.command).toBe('export_lpr_evidence')
    expect(fake.feedbacks).toContain('[export_lpr_evidence] disk full')
  })
})

describe('lprProgressEvent use-case', () => {
  it('skips payloads for another request', () => {
    const fake = createFakePorts()
    const result = runLprApplyProgressEvent({
      activeRequestId: 'req-active',
      payload: {
        requestId: 'req-other',
        progress: 0.3,
        stage: 'Frame',
        detail: 'Running',
        done: false,
        failed: false,
        reasonCode: null,
        trackingTier: null,
        coverageRatio: null,
      },
    }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.applied).toBe(false)
    expect(fake.calls).toHaveLength(0)
  })

  it('folds matching progress into a running job update', () => {
    const fake = createFakePorts()
    const result = runLprApplyProgressEvent({
      activeRequestId: 'req-1',
      payload: {
        requestId: 'req-1',
        progress: 0.5,
        stage: 'Frame',
        detail: 'Locating target',
        done: false,
        failed: false,
        reasonCode: null,
        trackingTier: null,
        coverageRatio: null,
      },
    }, fake.ports)

    expect(result.ok).toBe(true)
    if (!result.ok) {
      return
    }
    expect(result.data.applied).toBe(true)
    expect(lastJobPatch(fake.calls)).toMatchObject({ status: 'running', stage: 'Frame', requestId: 'req-1' })
  })
})
