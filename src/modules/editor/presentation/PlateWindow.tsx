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
  Eye,
  FileOutput,
  Globe,
  Image,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Search,
  Target,
  X,
  Zap,
} from 'lucide-react';
import {
  samplePrimaryText,
  PLATE_SESSION_UPDATED_EVENT,
  type PlateWindowSessionSnapshot,
} from '../application/plateWindow';
import { requestPlateWindowSession, sendPlateWindowAction } from '../infrastructure/plateWindowApi';
import { buildDefaultLprState, clamp, formatRulerLabel, formatTransportTime } from '../domain/model';
import type { LprFrameSample, LprPlateCandidate, TimelineIntervalSelection } from '../../../shared/contracts';
import { createLogger, getErrorSummary, serializeError } from '../../../utils/logger';
import styles from './PlateWindow.module.css';

const log = createLogger('PlateWindow');

function formatConfidence(confidence: number) {
  return `${Math.round(clamp(confidence, 0, 1) * 100)}%`;
}

function formatIntervalLabel(interval: TimelineIntervalSelection | null) {
  if (!interval) {
    return '--';
  }
  return `${formatTransportTime(interval.startMs)} - ${formatTransportTime(interval.endMs)}`;
}

function formatSampleTimestamp(milliseconds: number) {
  return formatRulerLabel(milliseconds);
}

type TabType = 'candidates' | 'targets' | 'evidence' | 'samples' | 'history';

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

function evidenceReason(entry: EvidenceSample) {
  if (entry.matchingCandidate) {
    return `Matched ${entry.matchingCandidate.text} with ${formatConfidence(entry.matchingCandidate.confidence)}`;
  }
  return `Top OCR sample ${samplePrimaryText(entry.sample)}`;
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

function formatReviewReason(reason: string) {
  switch (reason) {
    case 'low-confidence':
      return 'low confidence';
    case 'low-margin':
      return 'small margin';
    case 'insufficient-support':
      return 'weak support';
    case 'format-mismatch':
      return 'format mismatch';
    case 'no-candidate':
      return 'no candidate';
    default:
      return reason.replace(/-/g, ' ');
  }
}

function candidateBadgeLabel(candidate: LprPlateCandidate, acceptedCandidateId: string | null) {
  const selection = candidateSelection(candidate);
  const confidenceLabel = formatConfidence(candidate.confidence);
  if (selection.reviewRequired && selection.isSuggested && acceptedCandidateId === null) {
    return `${confidenceLabel} Review`;
  }
  if (selection.isAccepted || candidate.id === acceptedCandidateId) {
    return `${confidenceLabel} Accepted`;
  }
  if (selection.isSuggested) {
    return `${confidenceLabel} Suggested`;
  }
  return confidenceLabel;
}

export const PlateWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<PlateWindowSessionSnapshot | null>(null);
  const [countryHintsDraft, setCountryHintsDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [activeTab, setActiveTab] = React.useState<TabType>('candidates');
  const [selectedEvidenceSampleId, setSelectedEvidenceSampleId] = React.useState<string | null>(null);
  const [isEvidenceSelectionPinned, setIsEvidenceSelectionPinned] = React.useState(false);

  const lprState = snapshot?.lpr ?? buildDefaultLprState();
  const runtimeStatus = snapshot?.runtimeStatus ?? null;
  const topCandidate = snapshot?.topCandidate ?? lprState.candidates[0] ?? null;
  const isBusy = lprState.job.status === 'queued' || lprState.job.status === 'running';
  const currentPlayheadMs = snapshot?.playheadMs ?? 0;
  const evidenceSamples = React.useMemo(() => buildEvidenceSamples(lprState.samples, topCandidate), [lprState.samples, topCandidate]);
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
    let disposed = false;
    let removeSessionListener: (() => void) | undefined;

    void listen<PlateWindowSessionSnapshot>(PLATE_SESSION_UPDATED_EVENT, (event) => {
      if (disposed) return;
      setSnapshot(event.payload);
      setErrorMessage(null);
    }).then((unlisten) => {
      removeSessionListener = unlisten;
    });

    void requestPlateWindowSession().catch((error) => {
      if (disposed) return;
      log.error('Failed to request the latest plate window session.', serializeError(error));
      setErrorMessage(getErrorSummary(error, 'Unable to connect to the main editor window.'));
    });

    return () => {
      disposed = true;
      removeSessionListener?.();
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
            <section className={styles.hero}>
              <div className={styles.heroGlow} />
              <div className={styles.heroContent}>
                <div className={styles.heroMain}>
                  <AnimatePresence mode="popLayout">
                    <motion.div key={topCandidate?.text ?? 'empty'} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} className={styles.heroResultText}>
                      {topCandidate?.text ?? '--'}
                    </motion.div>
                  </AnimatePresence>
                  <AnimatePresence mode="popLayout">
                    <motion.div key={topCandidate ? formatConfidence(topCandidate.confidence) : '0'} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }} className={styles.heroResultConfidence}>
                      {topCandidate ? formatConfidence(topCandidate.confidence) : '0%'}
                    </motion.div>
                  </AnimatePresence>
                </div>
              </div>
              <div className={styles.heroStatus}>
                <div className={styles.statusLine}>
                  {isBusy ? <LoaderCircle size={14} className={styles.spinningIcon} /> : topCandidate ? <Check size={14} className={styles.successIcon} /> : <AlertCircle size={14} className={styles.idleIcon} />}
                  <AnimatePresence mode="popLayout">
                    <motion.span key={lprState.job.detail || 'Ready.'} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                      {lprState.job.detail || runtimeStatus?.detail || 'Ready for analysis.'}
                    </motion.span>
                  </AnimatePresence>
                </div>
                <AnimatePresence>
                  {(lprState.job.error || errorMessage) && (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className={styles.errorBanner}>
                      <AlertCircle size={12} />
                      {lprState.job.error ?? errorMessage}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </section>

            {/* ACTION TOOLBAR */}
            <section className={styles.actionToolbar}>
              <div className={styles.primaryActions}>
                <motion.button whileTap={{ scale: 0.97 }} type="button" className={styles.actionBtnPrimary} onClick={() => void sendAction({ type: 'scan-targets' })} disabled={isBusy}>
                  <Target size={16} /> Targets
                </motion.button>
                <motion.button whileTap={{ scale: 0.97 }} type="button" className={styles.actionBtnPrimary} onClick={() => void sendAction({ type: 'analyze-frame' })} disabled={isBusy}>
                  <Search size={16} /> Frame
                </motion.button>
                <motion.button whileTap={{ scale: 0.97 }} type="button" className={styles.actionBtnPrimary} onClick={() => void sendAction({ type: 'analyze-range' })} disabled={!snapshot.canAnalyzeRange || isBusy}>
                  <Crop size={16} /> Range
                </motion.button>
              </div>

              <div className={styles.utilityActions}>
                <motion.button whileTap={{ scale: 0.95 }} type="button" className={`${styles.actionBtnUtility} ${lprState.useDenseSampling ? styles.utilityActive : ''}`} onClick={() => void sendAction({ type: 'toggle-dense-sampling' })} title="Toggle Dense Sampling">
                  <Database size={15} />
                </motion.button>
                <motion.button whileTap={{ scale: 0.95 }} type="button" className={styles.actionBtnUtility} onClick={() => void sendAction({ type: 'export-evidence' })} disabled={!topCandidate && lprState.samples.length === 0} title="Export Evidence">
                  <FileOutput size={15} />
                </motion.button>
                <motion.button whileTap={{ scale: 0.95 }} type="button" className={styles.actionBtnUtility} onClick={() => void sendAction({ type: 'clear-results' })} disabled={lprState.candidates.length === 0 && lprState.targetTracks.length === 0} title="Reset Results">
                  <RotateCcw size={15} />
                </motion.button>
              </div>
            </section>

            {/* CONFIGURATION BAR */}
            <section className={styles.configBar}>
              <div className={styles.segmentedControl}>
                <button type="button" onClick={() => void sendAction({ type: 'use-clip-interval' })}>Clip</button>
                <div className={styles.segmentDivider} />
                <button type="button" onClick={() => void sendAction({ type: 'set-interval-boundary', boundary: 'start' })}>In</button>
                <div className={styles.segmentDivider} />
                <button type="button" onClick={() => void sendAction({ type: 'set-interval-boundary', boundary: 'end' })}>Out</button>
                <div className={styles.segmentDivider} />
                <button type="button" onClick={() => void sendAction({ type: 'clear-interval' })} disabled={!snapshot.explicitInterval}>Clear</button>
              </div>
              <div className={styles.intervalBadge}>
                <Clock size={12} className={styles.mutedIcon} />
                <span>{formatIntervalLabel(snapshot.effectiveInterval)}</span>
              </div>
              <div className={styles.inputWrapper}>
                <Globe size={14} className={styles.inputIcon} />
                <input
                  type="text"
                  className={styles.input}
                  value={countryHintsDraft}
                  onChange={(event) => setCountryHintsDraft(event.target.value)}
                  onBlur={() => void sendAction({ type: 'set-country-hints', value: countryHintsDraft })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      void sendAction({ type: 'set-country-hints', value: countryHintsDraft });
                      event.currentTarget.blur();
                    }
                  }}
                  placeholder="tw, eu, us..."
                />
              </div>
            </section>

            {/* DATA VIEWER (TABS) */}
            <section className={styles.dataViewer}>
              <div className={styles.tabHeader}>
                <button type="button" className={`${styles.tabBtn} ${activeTab === 'candidates' ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab('candidates')}>
                  Candidates {lprState.candidates.length > 0 && <span className={styles.tabCount}>{lprState.candidates.length}</span>}
                  {activeTab === 'candidates' && <motion.div layoutId="activeTabIndicator" className={styles.activeTabIndicator} />}
                </button>
                <button type="button" className={`${styles.tabBtn} ${activeTab === 'targets' ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab('targets')}>
                  Targets {lprState.targetTracks.length > 0 && <span className={styles.tabCount}>{lprState.targetTracks.length}</span>}
                  {activeTab === 'targets' && <motion.div layoutId="activeTabIndicator" className={styles.activeTabIndicator} />}
                </button>
                <button type="button" className={`${styles.tabBtn} ${activeTab === 'evidence' ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab('evidence')}>
                  Evidence {evidenceSamples.length > 0 && <span className={styles.tabCount}>{evidenceSamples.length}</span>}
                  {activeTab === 'evidence' && <motion.div layoutId="activeTabIndicator" className={styles.activeTabIndicator} />}
                </button>
                <button type="button" className={`${styles.tabBtn} ${activeTab === 'samples' ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab('samples')}>
                  Samples {lprState.samples.length > 0 && <span className={styles.tabCount}>{lprState.samples.length}</span>}
                  {activeTab === 'samples' && <motion.div layoutId="activeTabIndicator" className={styles.activeTabIndicator} />}
                </button>
                <button type="button" className={`${styles.tabBtn} ${activeTab === 'history' ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab('history')}>
                  History
                  {activeTab === 'history' && <motion.div layoutId="activeTabIndicator" className={styles.activeTabIndicator} />}
                </button>
              </div>

              <div className={styles.tabContent}>
                <AnimatePresence mode="wait">
                  {/* CANDIDATES TAB */}
                  {activeTab === 'candidates' && (
                    <motion.div key="candidates" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.listContainer}>
                      {lprState.candidates.length === 0 && <div className={styles.emptyInline}>No candidates discovered.</div>}
                      {lprState.candidates.map((candidate) => {
                        const selection = candidateSelection(candidate);
                        const isActive = candidate.id === lprState.acceptedCandidateId || (lprState.acceptedCandidateId === null && selection.isSuggested);
                        return (
                          <motion.button
                            layout
                            variants={listItemVariants}
                            whileTap={{ scale: 0.98 }}
                            key={candidate.id}
                            type="button"
                            className={`${styles.listItemBtn} ${isActive ? styles.listItemBtnActive : ''}`}
                            onClick={() => void sendAction({ type: 'accept-candidate', candidateId: candidate.id })}
                          >
                            <span className={styles.listItemMainText}>{candidate.text}</span>
                            <span className={styles.listItemBadge}>{candidateBadgeLabel(candidate, lprState.acceptedCandidateId)}</span>
                            {isActive && <motion.div layoutId="activeCandidate" className={styles.activeListItemGlow} />}
                          </motion.button>
                        );
                      })}
                      {topCandidate && candidateSelection(topCandidate).reviewRequired && lprState.acceptedCandidateId === null && (
                        <div className={styles.emptyInline}>Review needed: {candidateSelection(topCandidate).reasons.map(formatReviewReason).join(', ') || 'manual confirmation required'}.</div>
                      )}
                    </motion.div>
                  )}

                  {/* TARGETS TAB */}
                  {activeTab === 'targets' && (
                    <motion.div key="targets" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.listContainer}>
                      {lprState.targetTracks.length === 0 && <div className={styles.emptyInline}>No tracking targets found.</div>}
                      {lprState.targetTracks.map((track) => (
                        <motion.button
                          layout
                          variants={listItemVariants}
                          whileTap={{ scale: 0.98 }}
                          key={track.id}
                          type="button"
                          className={`${styles.listItemBtn} ${track.id === lprState.selectedTargetTrackId ? styles.listItemBtnActive : ''}`}
                          onClick={() => void sendAction({ type: 'select-target-track', targetTrackId: track.id })}
                        >
                          <span className={styles.listItemMainText}>{track.label}</span>
                          <span className={styles.listItemBadge}>{formatConfidence(track.confidence)}</span>
                          {track.id === lprState.selectedTargetTrackId && <motion.div layoutId="activeTarget" className={styles.activeListItemGlow} />}
                        </motion.button>
                      ))}
                    </motion.div>
                  )}

                  {activeTab === 'evidence' && (
                    <motion.div key="evidence" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.evidenceLayout}>
                      {evidenceSamples.length === 0 && <div className={styles.emptyInline}>No evidence frames with saved artifacts yet. Enable artifact persistence or run frame/range analysis.</div>}
                      {evidenceSamples.length > 0 && activeEvidenceSample && (
                        <>
                          <div className={styles.evidenceRail}>
                            {evidenceSamples.map((entry) => (
                              <motion.button
                                layout
                                variants={listItemVariants}
                                whileTap={{ scale: 0.98 }}
                                key={entry.sample.id}
                                type="button"
                                className={`${styles.evidenceChip} ${entry.sample.id === activeEvidenceSample.sample.id ? styles.evidenceChipActive : ''}`}
                                onClick={() => {
                                  setSelectedEvidenceSampleId(entry.sample.id);
                                  setIsEvidenceSelectionPinned(true);
                                }}
                              >
                                <div className={styles.evidenceChipTopRow}>
                                  <span className={styles.evidenceChipTime}>{formatSampleTimestamp(entry.sample.timeMs)}</span>
                                  <span className={styles.evidenceChipBadge}>{formatConfidence(entry.sample.quality?.overallScore ?? 0)}</span>
                                </div>
                                <strong className={styles.evidenceChipText}>{entry.matchingCandidate?.text ?? samplePrimaryText(entry.sample)}</strong>
                                <span className={styles.evidenceChipReason}>{evidenceReason(entry)}</span>
                              </motion.button>
                            ))}
                          </div>

                          <div className={styles.evidenceCard}>
                            <div className={styles.evidenceCardHeader}>
                              <div>
                                <div className={styles.evidenceCardTitleRow}>
                                  <Eye size={14} className={styles.mutedIcon} />
                                  <strong>Decision Frame {formatSampleTimestamp(activeEvidenceSample.sample.timeMs)}</strong>
                                </div>
                                <span className={styles.evidenceCardSubtitle}>{evidenceReason(activeEvidenceSample)}</span>
                              </div>
                              <button
                                type="button"
                                className={styles.evidenceJumpButton}
                                onClick={() => void handleSeekToSample(activeEvidenceSample.sample.id, activeEvidenceSample.sample.timeMs)}
                              >
                                Jump To Frame
                              </button>
                            </div>

                            <div className={styles.evidencePreviewGrid}>
                              {activeEvidenceSample.artifacts.map((artifact) => (
                                <div key={artifact.key} className={styles.evidencePreviewCard}>
                                  <div className={styles.evidencePreviewLabel}><Image size={12} className={styles.mutedIcon} /> {artifact.label}</div>
                                  <img className={styles.evidencePreviewImage} src={toImageSrc(artifact.path)} alt={`${artifact.label} ${formatSampleTimestamp(activeEvidenceSample.sample.timeMs)}`} />
                                </div>
                              ))}
                            </div>

                            <div className={styles.evidenceMetaGrid}>
                              <div className={styles.evidenceMetaSection}>
                                <div className={styles.evidenceMetaTitle}>Quality</div>
                                <div className={styles.evidenceMetricList}>
                                  {qualityMetrics(activeEvidenceSample.sample).map(([label, value]) => (
                                    <div key={label} className={styles.evidenceMetricRow}>
                                      <span>{label}</span>
                                      <strong>{formatMetric(value)}</strong>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              <div className={styles.evidenceMetaSection}>
                                <div className={styles.evidenceMetaTitle}>Top OCR Outputs</div>
                                <div className={styles.evidenceCandidateList}>
                                  {evidenceCandidates(activeEvidenceSample.sample).map((candidate) => (
                                    <div key={candidate.id} className={styles.evidenceCandidateRow}>
                                      <span>{candidate.text}</span>
                                      <strong>{formatConfidence(candidate.confidence)}</strong>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          </div>
                        </>
                      )}
                    </motion.div>
                  )}

                  {/* SAMPLES TAB */}
                  {activeTab === 'samples' && (
                    <motion.div key="samples" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.listContainer}>
                      {lprState.samples.length === 0 && <div className={styles.emptyInline}>No extracted samples.</div>}
                      {lprState.samples.map((sample) => (
                        <motion.div
                          layout
                          variants={listItemVariants}
                          key={sample.id}
                          className={`${styles.infoItemRow} ${sample.timeMs === currentPlayheadMs ? styles.infoItemRowActive : ''}`}
                        >
                          <div className={styles.infoItemMeta}>
                            <Clock size={12} className={styles.mutedIcon} />
                            <button
                              type="button"
                              className={styles.infoItemTimeButton}
                              onClick={() => void handleSeekToSample(sample.id, sample.timeMs)}
                              title={`Jump to ${formatSampleTimestamp(sample.timeMs)}`}
                            >
                              <span className={styles.infoItemTime}>{formatSampleTimestamp(sample.timeMs)}</span>
                            </button>
                          </div>
                          <span className={styles.infoItemText}>{samplePrimaryText(sample)}</span>
                          <span className={styles.infoItemBadge}>Q: {formatConfidence(sample.quality?.overallScore ?? 0)}</span>
                          {sample.timeMs === currentPlayheadMs && <motion.div layoutId="activeSample" className={styles.activeListItemGlow} />}
                        </motion.div>
                      ))}
                    </motion.div>
                  )}

                  {/* HISTORY TAB */}
                  {activeTab === 'history' && (
                    <motion.div key="history" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.listContainer}>
                      {lprState.history.length === 0 && <div className={styles.emptyInline}>No previous actions.</div>}
                      {lprState.history.slice().reverse().map((entry) => (
                        <motion.div layout variants={listItemVariants} key={entry.id} className={styles.infoItemRow}>
                          <span className={styles.infoItemText}>{entry.summary}</span>
                          <span className={styles.infoItemPill}>{entry.interval ? formatIntervalLabel(entry.interval) : 'frame'}</span>
                        </motion.div>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </section>

          </motion.div>
        )}
      </div>
    </div>
  );
};
