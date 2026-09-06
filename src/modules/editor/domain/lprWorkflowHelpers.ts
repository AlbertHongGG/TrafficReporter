import type { TimelineIntervalSelection } from './model';
import type {
  LprPlateCandidate,
  LprReviewState,
  LprTargetTrack,
  LprTrackedRegion,
} from './lprState';

export type StageTimedJobLike = {
  status: string;
  stage: string;
  requestId: string | null;
  startedAt: string | null;
  stageStartedAt?: string | null;
};

export function isActiveJobStatus(status: string | null | undefined) {
  return status === 'queued' || status === 'running';
}

export function resolveStageStartedAt<TJob extends StageTimedJobLike>(
  currentJob: TJob,
  nextJob: Partial<TJob>,
  timestamp: string,
) {
  if (nextJob.stageStartedAt !== undefined) {
    return nextJob.stageStartedAt;
  }

  const nextStatus = nextJob.status ?? currentJob.status;
  const nextStage = nextJob.stage ?? currentJob.stage;
  const nextRequestId = nextJob.requestId ?? currentJob.requestId;
  const shouldResetStageClock = (
    nextRequestId !== currentJob.requestId
    || (typeof nextJob.stage === 'string' && nextStage !== currentJob.stage)
    || (!isActiveJobStatus(currentJob.status) && isActiveJobStatus(nextStatus))
    || currentJob.stageStartedAt === null
    || currentJob.stageStartedAt === undefined
  );

  if (isActiveJobStatus(nextStatus)) {
    return shouldResetStageClock ? timestamp : (currentJob.stageStartedAt ?? currentJob.startedAt ?? timestamp);
  }

  return currentJob.stageStartedAt ?? null;
}

export function formatLprReviewReason(reason: string) {
  switch (reason) {
    case 'low-confidence':
      return 'confidence stayed low';
    case 'low-margin':
      return 'the runner-up stayed too close';
    case 'insufficient-support':
      return 'too few sampled frames agreed';
    case 'format-mismatch':
      return 'the plate pattern looked off';
    case 'no-candidate':
      return 'no readable candidate was found';
    default:
      return reason.replace(/-/g, ' ');
  }
}

export function buildLprCompletionDetail(
  candidates: LprPlateCandidate[],
  review: LprReviewState | null | undefined,
) {
  const suggestedCandidate = candidates.find((candidate) => candidate.id === review?.suggestedCandidateId)
    ?? candidates[0]
    ?? null;
  if (!suggestedCandidate) {
    return 'No confident plate candidate.';
  }

  if (review?.status === 'review-required') {
    const acceptedCandidate = candidates.find((candidate) => candidate.id === review.acceptedCandidateId)
      ?? suggestedCandidate;
    const reasonLabel = review.reasons.map(formatLprReviewReason).join(', ') || 'manual review required';
    return `Best current read ${acceptedCandidate.text}. Auto-accept is paused because ${reasonLabel}.`;
  }

  const acceptedCandidate = candidates.find((candidate) => candidate.id === review?.acceptedCandidateId)
    ?? suggestedCandidate;
  return `Accepted ${acceptedCandidate.text}`;
}

export function buildAiEvidenceProjectionDetail(
  candidates: LprPlateCandidate[],
  review: LprReviewState | null | undefined,
  targetTracks: LprTargetTrack[],
) {
  const completionDetail = buildLprCompletionDetail(candidates, review);
  if (completionDetail) {
    return completionDetail;
  }
  if (targetTracks.length > 0) {
    return `Resolved ${targetTracks.length} target ${targetTracks.length === 1 ? 'candidate' : 'candidates'}.`;
  }
  return 'AI evidence projection ready.';
}

export function buildTargetTracksFromDetections(detections: LprTrackedRegion[]): LprTargetTrack[] {
  return detections.map((detection, index) => ({
    id: detection.id,
    className: detection.className,
    label: `${detection.className} ${index + 1}`,
    confidence: detection.confidence,
    frames: [detection],
  }));
}

export function normalizeLprInterval(interval: TimelineIntervalSelection): TimelineIntervalSelection {
  const startMs = Math.max(0, Math.round(interval.startMs));
  const endMs = Math.max(0, Math.round(interval.endMs));

  return {
    startMs: Math.min(startMs, endMs),
    endMs: Math.max(startMs, endMs),
  };
}

export function isAnchorWithinInterval(anchorTimeMs: number, interval: TimelineIntervalSelection) {
  return anchorTimeMs >= interval.startMs && anchorTimeMs <= interval.endMs;
}
