import React from 'react';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertCircle,
  Check,
  FileOutput,
  LoaderCircle,
  RefreshCw,
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
import { buildDefaultLprState, clamp, formatTransportTime } from '../domain/model';
import type { TimelineIntervalSelection } from '../../../shared/contracts';
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

const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.05,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 400, damping: 30 } },
};

const listExitVariants = {
  hidden: { opacity: 0, x: -10, scale: 0.95 },
  show: { opacity: 1, x: 0, scale: 1, transition: { type: 'spring', stiffness: 400, damping: 30 } },
  exit: { opacity: 0, scale: 0.95, transition: { duration: 0.15 } },
};

export const PlateWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<PlateWindowSessionSnapshot | null>(null);
  const [countryHintsDraft, setCountryHintsDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  const lprState = snapshot?.lpr ?? buildDefaultLprState();
  const runtimeStatus = snapshot?.runtimeStatus ?? null;
  const topCandidate = snapshot?.topCandidate ?? lprState.candidates[0] ?? null;
  const isBusy = lprState.job.status === 'queued' || lprState.job.status === 'running';

  React.useEffect(() => {
    let disposed = false;
    let removeSessionListener: (() => void) | undefined;

    void listen<PlateWindowSessionSnapshot>(PLATE_SESSION_UPDATED_EVENT, (event) => {
      if (disposed) {
        return;
      }

      setSnapshot(event.payload);
      setErrorMessage(null);
    }).then((unlisten) => {
      removeSessionListener = unlisten;
    });

    void requestPlateWindowSession().catch((error) => {
      if (disposed) {
        return;
      }

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

  const sendAction = React.useCallback(async (action: Parameters<typeof sendPlateWindowAction>[0]) => {
    try {
      await sendPlateWindowAction(action);
      setErrorMessage(null);
    } catch (error) {
      log.error('Failed to send a plate window action.', {
        action,
        error: serializeError(error),
      });
      setErrorMessage(getErrorSummary(error, 'Unable to send the plate action.'));
    }
  }, []);

  const closeWindow = React.useCallback(async () => {
    await getCurrentWindow().close();
  }, []);

  return (
    <div className={styles.window}>
      <div data-tauri-drag-region className={styles.chrome}>
        <div className={styles.chromeMeta} data-tauri-drag-region>
          <span className={styles.chromeTitle}>{snapshot?.activeFileName ?? 'Plate Editor'}</span>
          <span className={`${styles.runtimeBadge} ${runtimeStatus?.available ? styles.runtimeBadgeReady : styles.runtimeBadgeOffline}`}>
            {runtimeStatus?.available ? 'local runtime' : 'offline'}
          </span>
        </div>
        <div className={styles.chromeActions}>
          <motion.button whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }} type="button" className={styles.chromeButton} onClick={() => void sendAction({ type: 'refresh-runtime' })} aria-label="Refresh plate runtime">
            <RefreshCw size={14} />
          </motion.button>
          <motion.button whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }} type="button" className={`${styles.chromeButton} ${styles.chromeButtonClose}`} onClick={() => void closeWindow()} aria-label="Close plate window">
            <X size={14} />
          </motion.button>
        </div>
      </div>

      <div className={styles.body}>
        {!snapshot?.hasActiveFile && (
          <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className={styles.emptyState}>
            <div className={styles.emptyStateIcon}><Zap size={32} /></div>
            Import a file to start plate analysis.
          </motion.div>
        )}

        {snapshot?.hasActiveFile && (
          <motion.div className={styles.contentWrapper} variants={containerVariants} initial="hidden" animate="show">
            <motion.section variants={itemVariants} className={styles.block}>
              <div className={styles.intervalRow}>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'use-clip-interval' })}>
                  Clip
                </motion.button>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'set-interval-boundary', boundary: 'start' })}>
                  In
                </motion.button>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'set-interval-boundary', boundary: 'end' })}>
                  Out
                </motion.button>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'clear-interval' })} disabled={!snapshot.explicitInterval}>
                  Clear
                </motion.button>
              </div>
              <div className={styles.intervalValue}>
                <AnimatePresence mode="popLayout">
                  <motion.span
                    key={formatIntervalLabel(snapshot.effectiveInterval)}
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 10 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                    style={{ display: 'inline-block' }}
                  >
                    {formatIntervalLabel(snapshot.effectiveInterval)}
                  </motion.span>
                </AnimatePresence>
              </div>
            </motion.section>

            <motion.section variants={itemVariants} className={styles.block}>
              <div className={styles.inputWrapper}>
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
                  placeholder="e.g. tw, us, eu (country hints)"
                />
                <div className={styles.inputGlow} />
              </div>
            </motion.section>

            <motion.section variants={itemVariants} className={styles.block}>
              <div className={styles.actionGrid}>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.primaryButton} onClick={() => void sendAction({ type: 'scan-targets' })} disabled={isBusy}>
                  <Target size={14} className={styles.btnIcon} />
                  Targets
                </motion.button>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'analyze-frame' })} disabled={isBusy}>
                  <Search size={14} className={styles.btnIcon} />
                  Frame
                </motion.button>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'analyze-range' })} disabled={!snapshot.canAnalyzeRange || isBusy}>
                  <Target size={14} className={styles.btnIcon} />
                  Range
                </motion.button>
                <motion.button
                  whileTap={{ scale: 0.98 }}
                  type="button"
                  className={`${styles.toggleButton} ${lprState.useDenseSampling ? styles.toggleButtonActive : ''}`}
                  onClick={() => void sendAction({ type: 'toggle-dense-sampling' })}
                >
                  More Samples
                </motion.button>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'export-evidence' })} disabled={!topCandidate && lprState.samples.length === 0}>
                  <FileOutput size={14} className={styles.btnIcon} />
                  Evidence
                </motion.button>
                <motion.button whileTap={{ scale: 0.98 }} type="button" className={styles.secondaryButton} onClick={() => void sendAction({ type: 'clear-results' })} disabled={lprState.candidates.length === 0 && lprState.targetTracks.length === 0}>
                  <X size={14} className={styles.btnIcon} />
                  Reset
                </motion.button>
              </div>
            </motion.section>

            <motion.section variants={itemVariants} className={styles.block}>
              <div className={styles.statusRow}>
                {isBusy ? <LoaderCircle size={14} className={styles.spinningIcon} /> : topCandidate ? <Check size={14} className={styles.successIcon} /> : <AlertCircle size={14} className={styles.idleIcon} />}
                <AnimatePresence mode="popLayout">
                  <motion.span
                    key={lprState.job.detail || runtimeStatus?.detail || 'Local analysis ready.'}
                    initial={{ opacity: 0, filter: 'blur(4px)' }}
                    animate={{ opacity: 1, filter: 'blur(0px)' }}
                    exit={{ opacity: 0, filter: 'blur(4px)' }}
                  >
                    {lprState.job.detail || runtimeStatus?.detail || 'Local analysis ready.'}
                  </motion.span>
                </AnimatePresence>
              </div>
              <AnimatePresence>
                {(lprState.job.error || errorMessage) && (
                  <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className={styles.errorText}>
                    {lprState.job.error ?? errorMessage}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.section>

            <motion.section variants={itemVariants} className={styles.resultStripWrapper}>
              <div className={styles.resultStripGlow} />
              <div className={styles.resultStrip}>
                <div className={styles.resultPrimary}>
                  <AnimatePresence mode="popLayout">
                    <motion.span
                      key={topCandidate?.text ?? '--'}
                      initial={{ opacity: 0, y: 15 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -15 }}
                      style={{ display: 'inline-block' }}
                    >
                      {topCandidate?.text ?? '--'}
                    </motion.span>
                  </AnimatePresence>
                </div>
                <div className={styles.resultConfidence}>
                  <AnimatePresence mode="popLayout">
                    <motion.span
                      key={topCandidate ? formatConfidence(topCandidate.confidence) : '0%'}
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.8 }}
                      style={{ display: 'inline-block' }}
                    >
                      {topCandidate ? formatConfidence(topCandidate.confidence) : '0%'}
                    </motion.span>
                  </AnimatePresence>
                </div>
              </div>
            </motion.section>

            <motion.section variants={itemVariants} className={styles.listBlock}>
              <div className={styles.listHeader}>Candidates</div>
              <div className={styles.listBody}>
                <AnimatePresence mode="popLayout">
                  {lprState.candidates.length === 0 && <motion.div variants={listExitVariants} initial="hidden" animate="show" exit="exit" className={styles.emptyInline}>No candidates.</motion.div>}
                  {lprState.candidates.map((candidate) => (
                    <motion.button
                      layout
                      variants={listExitVariants}
                      initial="hidden"
                      animate="show"
                      exit="exit"
                      whileTap={{ scale: 0.98 }}
                      key={candidate.id}
                      type="button"
                      className={`${styles.listButton} ${candidate.id === lprState.acceptedCandidateId ? styles.listButtonActive : ''}`}
                      onClick={() => void sendAction({ type: 'accept-candidate', candidateId: candidate.id })}
                    >
                      <span className={styles.listButtonText}>{candidate.text}</span>
                      <span className={styles.listButtonBadge}>{formatConfidence(candidate.confidence)}</span>
                      {candidate.id === lprState.acceptedCandidateId && (
                        <motion.div layoutId="activeCandidateHighlight" className={styles.activeHighlight} />
                      )}
                    </motion.button>
                  ))}
                </AnimatePresence>
              </div>
            </motion.section>

            <motion.div variants={itemVariants} className={styles.splitColumns}>
              <section className={styles.listBlock}>
                <div className={styles.listHeader}>Targets</div>
                <div className={styles.listBody}>
                  <AnimatePresence mode="popLayout">
                    {lprState.targetTracks.length === 0 && <motion.div variants={listExitVariants} initial="hidden" animate="show" exit="exit" className={styles.emptyInline}>No targets.</motion.div>}
                    {lprState.targetTracks.map((track) => (
                      <motion.button
                        layout
                        variants={listExitVariants}
                        initial="hidden"
                        animate="show"
                        exit="exit"
                        whileTap={{ scale: 0.98 }}
                        key={track.id}
                        type="button"
                        className={`${styles.listButton} ${track.id === lprState.selectedTargetTrackId ? styles.listButtonActive : ''}`}
                        onClick={() => void sendAction({ type: 'select-target-track', targetTrackId: track.id })}
                      >
                        <span className={styles.listButtonText}>{track.label}</span>
                        <span className={styles.listButtonBadge}>{formatConfidence(track.confidence)}</span>
                        {track.id === lprState.selectedTargetTrackId && (
                          <motion.div layoutId="activeTargetHighlight" className={styles.activeHighlight} />
                        )}
                      </motion.button>
                    ))}
                  </AnimatePresence>
                </div>
              </section>

              <section className={`${styles.listBlock} ${styles.samplesBlock}`}>
                <div className={styles.listHeader}>Samples</div>
                <div className={`${styles.listBody} ${styles.samplesListBody}`}>
                  <AnimatePresence mode="popLayout">
                    {lprState.samples.length === 0 && <motion.div variants={listExitVariants} initial="hidden" animate="show" exit="exit" className={styles.emptyInline}>No samples.</motion.div>}
                    {lprState.samples.map((sample) => (
                      <motion.div layout variants={listExitVariants} initial="hidden" animate="show" exit="exit" key={sample.id} className={styles.sampleRow}>
                        <div className={styles.sampleMain}>
                          <span className={styles.sampleTime}>{formatTransportTime(sample.timeMs)}</span>
                          <span className={styles.sampleText}>{samplePrimaryText(sample)}</span>
                        </div>
                        <span className={styles.sampleBadge}>Q {formatConfidence(sample.quality?.overallScore ?? 0)}</span>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              </section>
            </motion.div>

            <motion.section variants={itemVariants} className={styles.listBlock}>
              <div className={styles.listHeader}>History</div>
              <div className={styles.listBody}>
                <AnimatePresence mode="popLayout">
                  {lprState.history.length === 0 && <motion.div variants={listExitVariants} initial="hidden" animate="show" exit="exit" className={styles.emptyInline}>No history.</motion.div>}
                  {lprState.history.slice().reverse().map((entry) => (
                    <motion.div layout variants={listExitVariants} initial="hidden" animate="show" exit="exit" key={entry.id} className={styles.historyRow}>
                      <span className={styles.historySummary}>{entry.summary}</span>
                      <span className={styles.historyInterval}>{entry.interval ? formatIntervalLabel(entry.interval) : 'frame'}</span>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            </motion.section>
          </motion.div>
        )}
      </div>
    </div>
  );
};
