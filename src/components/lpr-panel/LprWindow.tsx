// @ts-nocheck
﻿// @ts-nocheck
import React from 'react';
import { listen } from '@tauri-apps/api/event';
import { convertFileSrc } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import {
  AlertCircle,
  Check,
  Clock,
  Crop,
  Database,
  FileOutput,
  Globe,
  Image,
  LoaderCircle,
  LocateFixed,
  RefreshCw,
  RotateCcw,
  Search,
  Target,
  X,
  Zap,
} from 'lucide-react';
import { Select } from '../common/Select/Select';
import {
  PLATE_LIVE_TRANSPORT_EVENT,
  resolveLprDisplayCandidate,
  samplePrimaryText,
  PLATE_SESSION_UPDATED_EVENT,
  resolvePlateWindowPlayheadMs,
  type PlateWindowLiveTransport,
  type RevisionedPlateWindowSessionSnapshot,
  type PlateWindowSessionSnapshot,
} from '../../modules/editor/application/plateWindow';
import { buildJobTimingSnapshot, formatElapsedDuration } from '../../modules/editor/application/jobTiming';
import { requestPlateWindowSession, sendPlateWindowAction } from '../../modules/editor/infrastructure/plateWindowApi';
import { clamp, formatRulerLabel, formatRulerLabelWithMilliseconds } from '../../modules/editor/domain/model';
import { buildDefaultLprState } from '../../modules/editor/domain/lprState';
import type { LprFrameSample, LprJobState, LprPlateCandidate, LprReviewState, LprTargetTrack, TimelineIntervalSelection } from '../../shared/contracts';
import { getLprAnalysisProfileLabel, getLprAnalysisProfiles } from '../../shared/lprAnalysisProfiles';
import { createLogger, getErrorSummary, serializeError } from '../../utils/logger';
import { shouldApplyRevisionedWindowSnapshot, unwrapRevisionedWindowSnapshot } from '../../vnext/windowing/revisionedSnapshot';
import { LprDashboard } from './LprDashboard';
import { LprDataViewer } from './LprDataViewer';
import styles from './LprWindow.module.css';

const log = createLogger('PlateWindow');

function formatConfidence(confidence: number) {
  return `${Math.round(clamp(confidence, 0, 1) * 100)}%`;
}

function formatIntervalLabel(interval: TimelineIntervalSelection | null) {
  if (!interval) {
    return '--';
  }
  return `${formatRulerLabelWithMilliseconds(interval.startMs)} - ${formatRulerLabelWithMilliseconds(interval.endMs)}`;
}

function formatSampleTimestamp(milliseconds: number) {
  return formatRulerLabel(milliseconds);
}

function formatHistoryLabel(interval: TimelineIntervalSelection | null, analysisProfileId: string | null, developerDiagnosticsEnabled: boolean) {
  return [
    interval ? formatIntervalLabel(interval) : 'frame',
    getLprAnalysisProfileLabel(analysisProfileId),
    developerDiagnosticsEnabled ? 'dx' : null,
  ].filter(Boolean).join(' 繚 ');
}

type TabType = 'targets' | 'candidates' | 'evidence' | 'samples' | 'history';

type EvidenceArtifact = {
  key: string;
  label: string;
  path: string;
};

type EvidenceSample = {
  sample: LprFrameSample;
  matchingCandidate: LprPlateCandidate | null;
  artifacts: EvidenceArtifact[];
  score: number;
};

const tabContentVariants: Variants = {
  hidden: { opacity: 0, y: 10, filter: 'blur(4px)' },
  show: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { type: 'spring' as const, stiffness: 350, damping: 25 } },
  exit: { opacity: 0, y: -10, filter: 'blur(4px)', transition: { duration: 0.15 } },
};

const listItemVariants: Variants = {
  hidden: { opacity: 0, x: -10 },
  show: { opacity: 1, x: 0, transition: { type: 'spring' as const, stiffness: 400, damping: 30 } },
  exit: { opacity: 0, scale: 0.95, transition: { duration: 0.15 } },
};

function normalizePlateText(value: string | null | undefined) {
  return (value ?? '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === 'string' && entry.length > 0)
    : [];
}

function asArtifacts(sample: LprFrameSample): EvidenceArtifact[] {
  const diagnostics = asRecord(sample.diagnostics);
  const plateProcessing = asRecord(diagnostics?.plateProcessing);
  const artifacts = asRecord(plateProcessing?.artifacts);
  const result: EvidenceArtifact[] = [];
  for (const [key, label] of [
    ['original', 'Original'],
    ['rectified', 'Rectified'],
    ['enhanced', 'Enhanced'],
    ['restored', 'Restored'],
    ['temporal-restored', 'Temporal'],
    ['working', 'Working'],
  ] satisfies Array<[string, string]>) {
    const rawPath = artifacts?.[key];
    if (typeof rawPath === 'string' && rawPath) {
      result.push({ key, label, path: rawPath });
    }
  }

  if (result.length === 0 && sample.imagePath) {
    result.push({ key: 'working', label: 'Working', path: sample.imagePath });
  }
  return result;
}

function toImageSrc(path: string) {
  return convertFileSrc(path);
}

function scoreEvidenceSample(sample: LprFrameSample, acceptedText: string) {
  const normalizedAccepted = normalizePlateText(acceptedText);
  const matchingCandidate = sample.candidates.find((candidate) => normalizePlateText(candidate.text) === normalizedAccepted) ?? null;
  const primaryCandidate = sample.candidates[0] ?? null;
  const baseConfidence = matchingCandidate?.confidence ?? primaryCandidate?.confidence ?? 0;
  const qualityScore = sample.quality?.overallScore ?? 0;
  const artifactWeight = asArtifacts(sample).length > 0 ? 0.08 : 0;
  const exactBoost = matchingCandidate ? 0.22 : 0;
  return {
    matchingCandidate,
    score: (baseConfidence * 0.62) + (qualityScore * 0.30) + exactBoost + artifactWeight,
  };
}

function buildEvidenceSamples(samples: LprFrameSample[], topCandidate: LprPlateCandidate | null): EvidenceSample[] {
  const acceptedText = normalizePlateText(topCandidate?.text);
  return samples
    .map((sample) => {
      const { matchingCandidate, score } = scoreEvidenceSample(sample, acceptedText);
      return {
        sample,
        matchingCandidate,
        artifacts: asArtifacts(sample),
        score,
      } satisfies EvidenceSample;
    })
    .filter((entry) => entry.artifacts.length > 0 || entry.matchingCandidate !== null || entry.sample.candidates.length > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, 6);
}

function formatMetric(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '--';
  }
  return `${Math.round(clamp(value, 0, 1) * 100)}%`;
}

function qualityMetrics(sample: LprFrameSample): Array<[string, number | null | undefined]> {
  const quality = sample.quality;
  return [
    ['Sharpness', quality?.sharpness],
    ['Contrast', quality?.contrast],
    ['Angle', quality?.angleScore],
    ['Glare', quality?.glareScore],
    ['Legibility', quality?.legibilityScore],
  ];
}

function evidenceCandidates(sample: LprFrameSample) {
  return sample.candidates.slice(0, 3);
}

function compactProfileDescription(profileId: string, fallbackDescription: string) {
  switch (profileId) {
    case 'precision':
      return 'strict';
    case 'balanced':
      return 'default';
    case 'recovery':
      return 'loose';
    default:
      return fallbackDescription.length > 18 ? `${fallbackDescription.slice(0, 18)}...` : fallbackDescription;
  }
}

function candidateSelection(candidate: LprPlateCandidate | null | undefined) {
  const diagnostics = asRecord(candidate?.diagnostics);
  const selection = asRecord(diagnostics?.selection);
  const reasons = Array.isArray(selection?.reasons)
    ? selection.reasons.filter((reason): reason is string => typeof reason === 'string')
    : [];
  return {
    isAccepted: selection?.isAccepted === true,
    isSuggested: selection?.isSuggested === true,
    reviewRequired: selection?.reviewRequired === true,
    reasons,
  };
}

function countSummary(label: string, value: number | null) {
  return value !== null && value > 0 ? `${label} ${value}` : null;
}

function buildDirectionDiagnosticsLine(label: string, diagnostics: Record<string, unknown> | null, trackedFrames: number | null) {
  if (!diagnostics) {
    return '';
  }

  const processedFrames = asNumber(diagnostics.processedFrames);
  const softGapFrames = asNumber(diagnostics.softGapFrames);
  const rejectedFrames = asNumber(diagnostics.rejectedFrames);
  const uncertainOverflowFrames = asNumber(diagnostics.uncertainOverflowFrames);
  const detectionFallbackFrames = asNumber(diagnostics.detectionFallbackFrames);
  const lastProcessedTimeMs = asNumber(diagnostics.lastProcessedTimeMs);

  return [
    label,
    trackedFrames !== null ? `tracked ${trackedFrames}` : null,
    processedFrames !== null ? `processed ${processedFrames}` : null,
    countSummary('gap', softGapFrames),
    countSummary('reject', rejectedFrames),
    countSummary('overflow', uncertainOverflowFrames),
    countSummary('fallback', detectionFallbackFrames),
    lastProcessedTimeMs !== null ? `last ${lastProcessedTimeMs}ms` : null,
  ].filter(Boolean).join(' 繚 ');
}

function buildTargetDiagnosticsLines(track: LprTargetTrack | null): string[] {
  if (!track) {
    return [];
  }
  const diagnostics = asRecord(track.diagnostics);
  if (!diagnostics) {
    return [];
  }
  const targetDetection = asRecord(diagnostics.targetDetection);
  const trackerMode = typeof diagnostics.trackerMode === 'string' ? diagnostics.trackerMode : null;
  const canonicalTargetId = typeof diagnostics.canonicalTargetId === 'string' ? diagnostics.canonicalTargetId : track.id;
  const anchorDetectionId = typeof diagnostics.anchorDetectionId === 'string' ? diagnostics.anchorDetectionId : null;
  const anchorTrackId = typeof diagnostics.anchorTrackId === 'string' ? diagnostics.anchorTrackId : null;
  const matchedFrames = asNumber(diagnostics.matchedFrames);
  const trajectoryFrameCount = asNumber(diagnostics.trajectoryFrameCount);
  const requestedTrackingFrameCount = asNumber(diagnostics.requestedTrackingFrameCount);
  const requestedEvidenceSampleCount = asNumber(diagnostics.requestedEvidenceSampleCount);
  const trajectoryStepMs = asNumber(diagnostics.trajectoryStepMs);
  const backwardTrackedFrameCount = asNumber(diagnostics.backwardTrackedFrameCount);
  const forwardTrackedFrameCount = asNumber(diagnostics.forwardTrackedFrameCount);
  const reassociatedFrames = asNumber(diagnostics.reassociatedFrames);
  const detectionFallbackFrames = asNumber(diagnostics.detectionFallbackFrames);
  const uncertainFrames = asNumber(diagnostics.uncertainFrames);
  const sceneMotionFrames = asNumber(diagnostics.sceneMotionFrames);
  const identityBreaks = asNumber(diagnostics.identityBreaks);
  const suppressedDuplicates = asNumber(targetDetection?.suppressedDuplicateDetections);
  const terminationReasons = asStringArray(diagnostics.terminationReasons);
  const directionSummaries = asRecord(diagnostics.directionSummaries);
  const backwardSummary = buildDirectionDiagnosticsLine(
    'back',
    asRecord(directionSummaries?.backward),
    backwardTrackedFrameCount,
  );
  const forwardSummary = buildDirectionDiagnosticsLine(
    'fwd',
    asRecord(directionSummaries?.forward),
    forwardTrackedFrameCount,
  );

  const lines = [
    [
      canonicalTargetId ? `id ${canonicalTargetId}` : null,
      trackerMode ? `mode ${trackerMode}` : null,
      matchedFrames !== null ? `frames ${matchedFrames}` : null,
      trajectoryFrameCount !== null ? `trajectory ${trajectoryFrameCount}` : null,
    ].filter(Boolean).join(' 繚 '),
    [
      anchorDetectionId ? `anchor ${anchorDetectionId}` : null,
      anchorTrackId ? `track ${anchorTrackId}` : null,
      requestedTrackingFrameCount !== null ? `requested ${requestedTrackingFrameCount}` : null,
      requestedEvidenceSampleCount !== null ? `evidence ${requestedEvidenceSampleCount}` : null,
      trajectoryStepMs !== null ? `step ${trajectoryStepMs}ms` : null,
      countSummary('deduped', suppressedDuplicates),
    ].filter(Boolean).join(' 繚 '),
    [
      countSummary('fallback', detectionFallbackFrames),
      countSummary('reassoc', reassociatedFrames),
      countSummary('uncertain', uncertainFrames),
      countSummary('scene', sceneMotionFrames),
      countSummary('identity', identityBreaks),
      diagnostics.terminatedEarly === true ? 'stopped early' : null,
    ].filter(Boolean).join(' 繚 '),
    backwardSummary,
    forwardSummary,
    terminationReasons.length > 0 ? `stop ${terminationReasons.join(', ')}` : '',
  ];

  return lines.filter((line) => line.length > 0);
}

type StatusTone = 'neutral' | 'success' | 'warning' | 'danger';

function buildJobBadge(job: LprJobState): { label: string; tone: StatusTone } {
  if (job.status === 'running' || job.status === 'queued') {
    return { label: job.stage || 'Run', tone: 'warning' };
  }
  if (job.status === 'degraded') {
    return { label: 'Degraded', tone: 'warning' };
  }
  if (job.status === 'failed') {
    return { label: 'Fail', tone: 'danger' };
  }
  if (job.status === 'cancelled') {
    return { label: 'Stop', tone: 'neutral' };
  }
  if (job.status === 'completed') {
    return { label: 'Done', tone: 'success' };
  }
  return { label: 'Idle', tone: 'neutral' };
}

function buildReviewBadge(review: LprReviewState | null): { label: string; tone: StatusTone } | null {
  if (!review) {
    return null;
  }
  if (review.status === 'accepted') {
    return { label: 'Lock', tone: 'success' };
  }
  if (review.status === 'review-required') {
    return { label: 'Check', tone: 'warning' };
  }
  return { label: 'Empty', tone: 'neutral' };
}

function candidateBadgeLabel(candidate: LprPlateCandidate, acceptedCandidateId: string | null) {
  const confidenceLabel = formatConfidence(candidate.confidence);
  void acceptedCandidateId;
  return confidenceLabel;
}

function heroConfidenceLabel(candidate: LprPlateCandidate | null) {
  if (!candidate) {
    return '0%';
  }
  return formatConfidence(candidate.confidence);
}

function evidenceReasonLabel(reason: string) {
  switch (reason) {
    case 'interval-start':
      return 'Start';
    case 'interval-end':
      return 'End';
    case 'anchor':
      return 'Anchor';
    case 'scheduled-sample':
      return 'Schedule';
    case 'motion-hotspot':
      return 'Motion';
    case 'high-confidence':
      return 'Stable';
    case 'sharpness-peak':
      return 'Sharp';
    case 'temporal-burst':
      return 'Burst';
    default:
      return reason;
  }
}

function sampleReasonTokens(sample: LprFrameSample) {
  return (sample.selection?.reasons ?? []).map(evidenceReasonLabel).slice(0, 4);
}

function formatJobTiming(ms: number | null | undefined) {
  return formatElapsedDuration(ms);
}

export const PlateWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<PlateWindowSessionSnapshot | null>(null);
  const [countryHintsDraft, setCountryHintsDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [activeTab, setActiveTab] = React.useState<TabType>('targets');
  const [selectedEvidenceSampleId, setSelectedEvidenceSampleId] = React.useState<string | null>(null);
  const [isEvidenceSelectionPinned, setIsEvidenceSelectionPinned] = React.useState(false);
  const [clockNowMs, setClockNowMs] = React.useState(() => Date.now());
  const latestRevisionRef = React.useRef(0);
  const [liveTransport, setLiveTransport] = React.useState<PlateWindowLiveTransport | null>(null);

  const lprState = snapshot?.lpr ?? buildDefaultLprState();
  const runtimeStatus = snapshot?.runtimeStatus ?? null;
  const topCandidate = snapshot?.topCandidate ?? resolveLprDisplayCandidate(lprState.candidates, lprState.review, lprState.acceptedCandidateId);
  const analysisProfiles = getLprAnalysisProfiles();
  const isBusy = lprState.job.status === 'queued' || lprState.job.status === 'running';
  const currentPlayheadMs = resolvePlateWindowPlayheadMs(snapshot, liveTransport);
  const evidenceSamples = React.useMemo(() => buildEvidenceSamples(lprState.samples, topCandidate), [lprState.samples, topCandidate]);
  const jobBadge = React.useMemo(() => buildJobBadge(lprState.job), [lprState.job]);
  const reviewBadge = React.useMemo(() => buildReviewBadge(lprState.review), [lprState.review]);
  const evidenceCount = evidenceSamples.length > 0 ? evidenceSamples.length : lprState.samples.length;
  const statusDetail = lprState.job.detail || runtimeStatus?.detail || 'Ready for analysis.';
  const jobTiming = React.useMemo(() => buildJobTimingSnapshot(lprState.job, clockNowMs), [clockNowMs, lprState.job]);
  const playheadEvidenceSample = React.useMemo(
    () => evidenceSamples.find((entry) => entry.sample.timeMs === currentPlayheadMs) ?? null,
    [currentPlayheadMs, evidenceSamples],
  );
  const activeEvidenceSample = React.useMemo(() => {
    if (isEvidenceSelectionPinned && selectedEvidenceSampleId) {
      return evidenceSamples.find((entry) => entry.sample.id === selectedEvidenceSampleId) ?? playheadEvidenceSample ?? evidenceSamples[0] ?? null;
    }
    return playheadEvidenceSample ?? evidenceSamples[0] ?? null;
  }, [evidenceSamples, isEvidenceSelectionPinned, playheadEvidenceSample, selectedEvidenceSampleId]);

  React.useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | undefined;
    if (isBusy) {
      intervalId = setInterval(() => {
        setClockNowMs(Date.now());
      }, 200);
    } else {
      setClockNowMs(Date.now());
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [isBusy, lprState.job.startedAt, lprState.job.updatedAt]);

  React.useEffect(() => {
    let disposed = false;
    let removeSessionListener: (() => void) | undefined;
    let removeLiveTransportListener: (() => void) | undefined;

    void listen<PlateWindowSessionSnapshot | RevisionedPlateWindowSessionSnapshot>(PLATE_SESSION_UPDATED_EVENT, (event) => {
      if (disposed) return;
      const envelope = unwrapRevisionedWindowSnapshot(event.payload);
      if (!shouldApplyRevisionedWindowSnapshot(latestRevisionRef.current, envelope.revision)) {
        return;
      }
      latestRevisionRef.current = envelope.revision;
      setLiveTransport(null);
      setSnapshot(envelope.snapshot);
      setErrorMessage(null);
    }).then((unlisten) => {
      removeSessionListener = unlisten;
    });

    void listen<PlateWindowLiveTransport>(PLATE_LIVE_TRANSPORT_EVENT, (event) => {
      if (disposed) {
        return;
      }
      setLiveTransport(event.payload);
    }).then((unlisten) => {
      removeLiveTransportListener = unlisten;
    });

    void requestPlateWindowSession().catch((error) => {
      if (disposed) return;
      log.error('Failed to request the latest plate window session.', serializeError(error));
      setErrorMessage(getErrorSummary(error, 'Unable to connect to the main editor window.'));
    });

    return () => {
      disposed = true;
      removeSessionListener?.();
      removeLiveTransportListener?.();
    };
  }, []);

  React.useEffect(() => {
    setCountryHintsDraft((snapshot?.lpr.countryHints ?? []).join(', '));
  }, [snapshot?.activeFileName, snapshot?.lpr.countryHints]);

  // Auto-switch tabs based on workflow context changes
  React.useEffect(() => {
    if (lprState.workflowMode === 'target') setActiveTab('targets');
    if (lprState.workflowMode === 'review') setActiveTab('candidates');
  }, [lprState.workflowMode]);

  React.useEffect(() => {
    if (isEvidenceSelectionPinned && selectedEvidenceSampleId) {
      const stillExists = evidenceSamples.some((entry) => entry.sample.id === selectedEvidenceSampleId);
      if (!stillExists) {
        setIsEvidenceSelectionPinned(false);
      }
      return;
    }

    setSelectedEvidenceSampleId(playheadEvidenceSample?.sample.id ?? evidenceSamples[0]?.sample.id ?? null);
  }, [evidenceSamples, isEvidenceSelectionPinned, playheadEvidenceSample?.sample.id, selectedEvidenceSampleId]);

  const sendAction = React.useCallback(async (action: Parameters<typeof sendPlateWindowAction>[0]) => {
    try {
      await sendPlateWindowAction(action);
      setErrorMessage(null);
    } catch (error) {
      log.error('Failed to send a plate window action.', { action, error: serializeError(error) });
      setErrorMessage(getErrorSummary(error, 'Unable to send the plate action.'));
    }
  }, []);

  const closeWindow = React.useCallback(async () => {
    await getCurrentWindow().close();
  }, []);

  const handleSeekToSample = React.useCallback(async (sampleId: string, timeMs: number) => {
    await sendAction({ type: 'seek-to-sample', sampleId, timeMs });
  }, [sendAction]);

  return (
    <div className={styles.window}>
      <div data-tauri-drag-region className={styles.chrome}>
        <div className={styles.chromeMeta} data-tauri-drag-region>
          <span className={styles.chromeTitle}>{snapshot?.activeFileName ?? 'Inspector'}</span>
          <span className={`${styles.runtimeBadge} ${runtimeStatus?.available ? styles.runtimeBadgeReady : styles.runtimeBadgeOffline}`}>
            {runtimeStatus?.available ? 'Local Engine' : 'Offline'}
          </span>
        </div>
        <div className={styles.chromeActions}>
          <button type="button" className={styles.chromeButton} onClick={() => void sendAction({ type: 'refresh-runtime' })} aria-label="Refresh runtime" title="Refresh LPR Runtime">
            <RefreshCw size={14} />
          </button>
          <button type="button" className={`${styles.chromeButton} ${styles.chromeButtonClose}`} onClick={() => void closeWindow()} aria-label="Close">
            <X size={14} />
          </button>
        </div>
      </div>

      <div className={styles.body}>
        {!snapshot?.hasActiveFile && (
          <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className={styles.emptyState}>
            <div className={styles.emptyStateIcon}><Zap size={36} /></div>
            <p>Import a file to start analysis.</p>
          </motion.div>
        )}

        {snapshot?.hasActiveFile && (
          <motion.div className={styles.dashboard} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            
            {/* HERO SECTION */}
            <LprDashboard
              lprState={lprState}
              sendAction={sendAction}
              isBusy={isBusy}
              topCandidate={topCandidate}
              heroConfidenceLabel={heroConfidenceLabel}
              statusDetail={statusDetail}
              jobBadge={jobBadge}
              reviewBadge={reviewBadge}
              jobTiming={jobTiming}
              formatJobTiming={formatJobTiming}
              evidenceCount={evidenceCount}
              errorMessage={errorMessage}
              snapshot={snapshot}
              formatIntervalLabel={formatIntervalLabel}
              analysisProfiles={analysisProfiles}
              compactProfileDescription={compactProfileDescription}
              countryHintsDraft={countryHintsDraft}
              setCountryHintsDraft={setCountryHintsDraft}
            />

            {/* DATA VIEWER (TABS) */}
            <LprDataViewer
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              lprState={lprState}
              sendAction={sendAction}
              evidenceSamples={evidenceSamples}
              tabContentVariants={tabContentVariants}
              listItemVariants={listItemVariants}
              buildTargetDiagnosticsLines={buildTargetDiagnosticsLines}
              candidateBadgeLabel={candidateBadgeLabel}
              candidateSelection={candidateSelection}
              evidenceCandidates={evidenceCandidates}
              toImageSrc={toImageSrc}
              qualityMetrics={qualityMetrics}
              formatMetric={formatMetric}
              samplePrimaryText={samplePrimaryText}
              sampleReasonTokens={sampleReasonTokens}
              formatSampleTimestamp={formatSampleTimestamp}
              activeEvidenceSample={activeEvidenceSample}
              handleSeekToSample={handleSeekToSample}
              formatHistoryLabel={formatHistoryLabel}
              currentPlayheadMs={currentPlayheadMs}
            />

          </motion.div>
        )}
      </div>
    </div>
  );
};

