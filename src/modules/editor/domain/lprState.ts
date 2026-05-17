import type {
  LprFrameSample,
  LprJobState,
  LprPlateCandidate,
  LprResultHistoryEntry,
  LprSessionState,
  LprTargetTrack,
  TimelineIntervalSelection,
} from '../../../shared/contracts';
import { defaultLprAnalysisProfileId } from '../../../shared/lprAnalysisProfiles';

export const DEFAULT_LPR_JOB_STATE: LprJobState = {
  status: 'idle',
  progress: 0,
  stage: '',
  detail: '',
  requestId: null,
  error: null,
  startedAt: null,
  updatedAt: null,
};

function cloneIntervalSelection(interval: TimelineIntervalSelection | null) {
  return interval ? { ...interval } : null;
}

function cloneLprJobState(job: LprJobState) {
  return { ...job };
}

function cloneLprTargetTracks(targetTracks: LprTargetTrack[]) {
  return targetTracks.map((track) => ({
    ...track,
    frames: track.frames.map((frame) => ({
      ...frame,
      box: { ...frame.box },
    })),
  }));
}

function cloneLprPlateCandidates(candidates: LprPlateCandidate[]) {
  return candidates.map((candidate) => ({
    ...candidate,
    box: candidate.box ? { ...candidate.box } : null,
    quality: candidate.quality ? { ...candidate.quality } : null,
  }));
}

function cloneLprSamples(samples: LprFrameSample[]) {
  return samples.map((sample) => ({
    ...sample,
    targetBox: sample.targetBox ? { ...sample.targetBox } : null,
    plateBox: sample.plateBox ? { ...sample.plateBox } : null,
    quality: sample.quality ? { ...sample.quality } : null,
    candidates: cloneLprPlateCandidates(sample.candidates),
  }));
}

function cloneLprHistory(history: LprResultHistoryEntry[]) {
  return history.map((entry) => ({
    ...entry,
    interval: cloneIntervalSelection(entry.interval),
    candidates: cloneLprPlateCandidates(entry.candidates),
  }));
}

export function buildDefaultLprState(overrides: Partial<LprSessionState> = {}): LprSessionState {
  return {
    workflowMode: overrides.workflowMode ?? 'idle',
    interval: cloneIntervalSelection(overrides.interval ?? null),
    selectedAnalysisProfileId: overrides.selectedAnalysisProfileId ?? defaultLprAnalysisProfileId,
    showDeveloperDiagnostics: overrides.showDeveloperDiagnostics ?? false,
    targetVehicleKind: overrides.targetVehicleKind ?? 'vehicle',
    useDenseSampling: overrides.useDenseSampling ?? true,
    countryHints: [...(overrides.countryHints ?? [])],
    job: cloneLprJobState(overrides.job ?? DEFAULT_LPR_JOB_STATE),
    targetTracks: cloneLprTargetTracks(overrides.targetTracks ?? []),
    selectedTargetTrackId: overrides.selectedTargetTrackId ?? null,
    samples: cloneLprSamples(overrides.samples ?? []),
    candidates: cloneLprPlateCandidates(overrides.candidates ?? []),
    acceptedCandidateId: overrides.acceptedCandidateId ?? null,
    history: cloneLprHistory(overrides.history ?? []),
  };
}
