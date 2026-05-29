import type {
  LprDecisionTrace,
  LprAnalysisProvenance,
  LprFrameSample,
  LprJobState,
  LprPlateCandidate,
  LprReviewState,
  LprResultHistoryEntry,
  LprSessionState,
  LprTargetAnchor,
  LprTargetTrack,
  LprVehicleKind,
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
  reasonCode: null,
  startedAt: null,
  updatedAt: null,
  trackingTier: null,
  coverageRatio: null,
};

function cloneIntervalSelection(interval: TimelineIntervalSelection | null) {
  return interval ? { ...interval } : null;
}

function cloneLprJobState(job: LprJobState) {
  return { ...job };
}

function cloneLprReviewState(review: LprReviewState | null) {
  return review ? {
    ...review,
    reasons: [...review.reasons],
  } : null;
}

function cloneLprAnalysisProvenance(provenance: LprAnalysisProvenance | null) {
  return provenance ? { ...provenance } : null;
}

function cloneLprDecisionTrace(decision: LprDecisionTrace | null) {
  return decision ? { ...decision } : null;
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

function cloneLprTargetTrack(track: LprTargetTrack | null) {
  return track ? cloneLprTargetTracks([track])[0] ?? null : null;
}

function cloneLprTargetAnchor(anchor: LprTargetAnchor | null) {
  return anchor ? {
    ...anchor,
    box: { ...anchor.box },
  } : null;
}

function resolveAnchorFrame(
  track: Pick<LprTargetTrack, 'frames'>,
  preferredTimeMs: number | null | undefined,
) {
  if (track.frames.length === 0) {
    return null;
  }

  if (typeof preferredTimeMs !== 'number' || Number.isNaN(preferredTimeMs)) {
    return track.frames[0] ?? null;
  }

  return track.frames.reduce((closestFrame, candidateFrame) => (
    Math.abs(candidateFrame.timeMs - preferredTimeMs) < Math.abs(closestFrame.timeMs - preferredTimeMs)
      ? candidateFrame
      : closestFrame
  ));
}

export function buildLprTargetAnchor(
  track: Pick<LprTargetTrack, 'id' | 'className' | 'frames'> | null | undefined,
  preferredTimeMs?: number | null,
): LprTargetAnchor | null {
  if (!track) {
    return null;
  }

  const anchorFrame = resolveAnchorFrame(track, preferredTimeMs);
  if (!anchorFrame) {
    return null;
  }

  return {
    trackId: track.id,
    className: track.className,
    timeMs: anchorFrame.timeMs,
    box: { ...anchorFrame.box },
  };
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
    selection: sample.selection ? { ...sample.selection, reasons: [...sample.selection.reasons] } : null,
    ocrInput: sample.ocrInput ? { ...sample.ocrInput } : null,
    temporalSupport: sample.temporalSupport ? { ...sample.temporalSupport, supportTimes: [...sample.temporalSupport.supportTimes] } : null,
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

export function resolveLprAnalysisTargetVehicleKind(
  selectedTargetTrack: Pick<LprTargetTrack, 'className'> | null | undefined,
  fallbackVehicleKind: LprVehicleKind,
): LprVehicleKind {
  switch (selectedTargetTrack?.className) {
    case 'car':
    case 'motorcycle':
    case 'truck':
    case 'bus':
      return selectedTargetTrack.className;
    default:
      return fallbackVehicleKind;
  }
}

export function buildDefaultLprState(overrides: Partial<LprSessionState> = {}): LprSessionState {
  return {
    workflowMode: overrides.workflowMode ?? 'idle',
    interval: cloneIntervalSelection(overrides.interval ?? null),
    selectedAnalysisProfileId: overrides.selectedAnalysisProfileId ?? defaultLprAnalysisProfileId,
    showDeveloperDiagnostics: overrides.showDeveloperDiagnostics ?? true,
    targetVehicleKind: overrides.targetVehicleKind ?? 'vehicle',
    useDenseSampling: overrides.useDenseSampling ?? true,
    countryHints: [...(overrides.countryHints ?? [])],
    job: cloneLprJobState(overrides.job ?? DEFAULT_LPR_JOB_STATE),
    targetTracks: cloneLprTargetTracks(overrides.targetTracks ?? []),
    selectedTargetTrackId: overrides.selectedTargetTrackId ?? null,
    selectedTargetAnchor: cloneLprTargetAnchor(overrides.selectedTargetAnchor ?? null),
    analysisTrack: cloneLprTargetTrack(overrides.analysisTrack ?? null),
    samples: cloneLprSamples(overrides.samples ?? []),
    candidates: cloneLprPlateCandidates(overrides.candidates ?? []),
    review: cloneLprReviewState(overrides.review ?? null),
    lastAnalysisProvenance: cloneLprAnalysisProvenance(overrides.lastAnalysisProvenance ?? null),
    decision: cloneLprDecisionTrace(overrides.decision ?? null),
    acceptedCandidateId: overrides.acceptedCandidateId ?? null,
    history: cloneLprHistory(overrides.history ?? []),
  };
}
