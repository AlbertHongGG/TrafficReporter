import React from 'react';
import { listen } from '@tauri-apps/api/event';
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

type TabType = 'candidates' | 'targets' | 'samples' | 'history';

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

export const PlateWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<PlateWindowSessionSnapshot | null>(null);
  const [countryHintsDraft, setCountryHintsDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [activeTab, setActiveTab] = React.useState<TabType>('candidates');

  const lprState = snapshot?.lpr ?? buildDefaultLprState();
  const runtimeStatus = snapshot?.runtimeStatus ?? null;
  const topCandidate = snapshot?.topCandidate ?? lprState.candidates[0] ?? null;
  const isBusy = lprState.job.status === 'queued' || lprState.job.status === 'running';

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
                      {lprState.candidates.map((candidate) => (
                        <motion.button
                          layout
                          variants={listItemVariants}
                          whileTap={{ scale: 0.98 }}
                          key={candidate.id}
                          type="button"
                          className={`${styles.listItemBtn} ${candidate.id === lprState.acceptedCandidateId ? styles.listItemBtnActive : ''}`}
                          onClick={() => void sendAction({ type: 'accept-candidate', candidateId: candidate.id })}
                        >
                          <span className={styles.listItemMainText}>{candidate.text}</span>
                          <span className={styles.listItemBadge}>{formatConfidence(candidate.confidence)}</span>
                          {candidate.id === lprState.acceptedCandidateId && <motion.div layoutId="activeCandidate" className={styles.activeListItemGlow} />}
                        </motion.button>
                      ))}
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

                  {/* SAMPLES TAB */}
                  {activeTab === 'samples' && (
                    <motion.div key="samples" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.listContainer}>
                      {lprState.samples.length === 0 && <div className={styles.emptyInline}>No extracted samples.</div>}
                      {lprState.samples.map((sample) => (
                        <motion.div layout variants={listItemVariants} key={sample.id} className={styles.infoItemRow}>
                          <div className={styles.infoItemMeta}>
                            <Clock size={12} className={styles.mutedIcon} />
                            <span className={styles.infoItemTime}>{formatTransportTime(sample.timeMs)}</span>
                          </div>
                          <span className={styles.infoItemText}>{samplePrimaryText(sample)}</span>
                          <span className={styles.infoItemBadge}>Q: {formatConfidence(sample.quality?.overallScore ?? 0)}</span>
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
