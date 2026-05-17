import type {
  LprFrameSample,
  LprJobState,
  LprPlateCandidate,
  LprResultHistoryEntry,
  LprSessionState,
  LprTargetTrack,
  LprVehicleKind,
  LprWorkflowMode,
  TimelineIntervalSelection,
} from '../domain/model';
import type { LprAnalysisProvenance, LprReviewState } from '../../../shared/contracts';
import { buildDefaultLprState } from '../domain/lprState';

export type LprSessionAction =
  | { type: 'set-lpr-mode'; workflowMode: LprWorkflowMode }
  | { type: 'set-lpr-interval'; interval: TimelineIntervalSelection }
  | { type: 'clear-lpr-interval' }
  | { type: 'set-lpr-analysis-profile'; analysisProfileId: string }
  | { type: 'set-lpr-target-vehicle-kind'; targetVehicleKind: LprVehicleKind }
  | { type: 'set-lpr-country-hints'; countryHints: string[] }
  | {
      type: 'set-lpr-toggles';
      toggles: Partial<Pick<LprSessionState, 'useDenseSampling' | 'showDeveloperDiagnostics'>>;
    }
  | { type: 'set-lpr-target-tracks'; targetTracks: LprTargetTrack[] }
  | { type: 'set-lpr-analysis-track'; analysisTrack: LprTargetTrack | null }
  | { type: 'select-lpr-target-track'; targetTrackId: string | null }
  | { type: 'set-lpr-job'; job: Partial<LprJobState> }
  | { type: 'set-lpr-samples'; samples: LprFrameSample[] }
  | { type: 'set-lpr-candidates'; candidates: LprPlateCandidate[] }
  | { type: 'set-lpr-review'; review: LprReviewState | null }
  | { type: 'set-lpr-provenance'; provenance: LprAnalysisProvenance | null }
  | { type: 'accept-lpr-candidate'; candidateId: string | null }
  | { type: 'append-lpr-history'; entry: LprResultHistoryEntry }
  | { type: 'clear-lpr-results' }
  | { type: 'reset-lpr-session' };

const LPR_SESSION_ACTION_TYPES = new Set<LprSessionAction['type']>([
  'set-lpr-mode',
  'set-lpr-interval',
  'clear-lpr-interval',
  'set-lpr-analysis-profile',
  'set-lpr-target-vehicle-kind',
  'set-lpr-country-hints',
  'set-lpr-toggles',
  'set-lpr-target-tracks',
  'set-lpr-analysis-track',
  'select-lpr-target-track',
  'set-lpr-job',
  'set-lpr-samples',
  'set-lpr-review',
  'set-lpr-provenance',
  'set-lpr-candidates',
  'accept-lpr-candidate',
  'append-lpr-history',
  'clear-lpr-results',
  'reset-lpr-session',
]);

function reconcileReviewSelection(
  lprState: LprSessionState,
  candidateId: string | null,
): LprReviewState | null {
  if (!lprState.review) {
    return null;
  }

  if (!candidateId) {
    return {
      ...lprState.review,
      acceptedCandidateId: null,
      status: lprState.review.suggestedCandidateId ? 'review-required' : lprState.review.status,
    };
  }

  return {
    ...lprState.review,
    acceptedCandidateId: candidateId,
    status: 'accepted',
  };
}

export function isLprSessionAction(action: { type: string }): action is LprSessionAction {
  return LPR_SESSION_ACTION_TYPES.has(action.type as LprSessionAction['type']);
}

export function reduceLprSession(lprState: LprSessionState, action: LprSessionAction): LprSessionState {
  switch (action.type) {
    case 'set-lpr-mode':
      return {
        ...lprState,
        workflowMode: action.workflowMode,
      };

    case 'set-lpr-interval':
      return {
        ...lprState,
        interval: {
          startMs: Math.max(0, Math.min(action.interval.startMs, action.interval.endMs)),
          endMs: Math.max(0, Math.max(action.interval.startMs, action.interval.endMs)),
        },
        workflowMode: lprState.workflowMode === 'idle' ? 'range' : lprState.workflowMode,
      };

    case 'clear-lpr-interval':
      return {
        ...lprState,
        interval: null,
      };

    case 'set-lpr-analysis-profile':
      return {
        ...lprState,
        selectedAnalysisProfileId: action.analysisProfileId,
      };

    case 'set-lpr-target-vehicle-kind':
      return {
        ...lprState,
        targetVehicleKind: action.targetVehicleKind,
      };

    case 'set-lpr-country-hints':
      return {
        ...lprState,
        countryHints: [...action.countryHints],
      };

    case 'set-lpr-toggles':
      return {
        ...lprState,
        ...action.toggles,
      };

    case 'set-lpr-target-tracks':
      return {
        ...lprState,
        targetTracks: buildDefaultLprState({ targetTracks: action.targetTracks }).targetTracks,
        selectedTargetTrackId: action.targetTracks.some((track) => track.id === lprState.selectedTargetTrackId)
          ? lprState.selectedTargetTrackId
          : action.targetTracks[0]?.id ?? null,
      };

    case 'set-lpr-analysis-track':
      return {
        ...lprState,
        analysisTrack: buildDefaultLprState({ analysisTrack: action.analysisTrack }).analysisTrack,
      };

    case 'select-lpr-target-track':
      return {
        ...lprState,
        selectedTargetTrackId: action.targetTrackId,
        workflowMode: action.targetTrackId ? 'target' : lprState.workflowMode,
      };

    case 'set-lpr-job':
      return {
        ...lprState,
        job: {
          ...lprState.job,
          ...action.job,
        },
      };

    case 'set-lpr-samples':
      return {
        ...lprState,
        samples: buildDefaultLprState({ samples: action.samples }).samples,
      };

    case 'set-lpr-candidates':
      return {
        ...lprState,
        candidates: buildDefaultLprState({ candidates: action.candidates }).candidates,
        acceptedCandidateId: action.candidates.some((candidate) => candidate.id === lprState.acceptedCandidateId)
          ? lprState.acceptedCandidateId
          : action.candidates[0]?.id ?? null,
      };

    case 'set-lpr-review':
      return {
        ...lprState,
        review: action.review ? buildDefaultLprState({ review: action.review }).review : null,
      };

    case 'set-lpr-provenance':
      return {
        ...lprState,
        lastAnalysisProvenance: action.provenance ? buildDefaultLprState({ lastAnalysisProvenance: action.provenance }).lastAnalysisProvenance : null,
      };

    case 'accept-lpr-candidate':
      return {
        ...lprState,
        review: reconcileReviewSelection(lprState, action.candidateId),
        acceptedCandidateId: action.candidateId,
        workflowMode: action.candidateId ? 'review' : lprState.workflowMode,
      };

    case 'append-lpr-history':
      return {
        ...lprState,
        history: [...lprState.history, buildDefaultLprState({ history: [action.entry] }).history[0]],
      };

    case 'clear-lpr-results':
      return {
        ...lprState,
        job: buildDefaultLprState().job,
        targetTracks: [],
        selectedTargetTrackId: null,
        analysisTrack: null,
        samples: [],
        candidates: [],
        review: null,
        lastAnalysisProvenance: null,
        acceptedCandidateId: null,
      };

    case 'reset-lpr-session':
      return buildDefaultLprState();
  }
}
