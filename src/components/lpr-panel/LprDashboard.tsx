// @ts-nocheck
import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, Check, Clock, Crop, Database, FileOutput, Globe, Image, LoaderCircle, RotateCcw, Search, Target, X, Zap } from 'lucide-react';
import { Select } from '../common/Select/Select';
import styles from './LprWindow.module.css';

export const LprDashboard = ({
  lprState, sendAction, isBusy, topCandidate, heroConfidenceLabel, statusDetail, jobBadge, reviewBadge,
  jobTiming, formatJobTiming, evidenceCount, errorMessage, snapshot, formatIntervalLabel, analysisProfiles,
  compactProfileDescription, countryHintsDraft, setCountryHintsDraft
}) => {
  return (
    <>
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
              <motion.div key={heroConfidenceLabel(topCandidate)} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }} className={styles.heroResultConfidence}>
                {heroConfidenceLabel(topCandidate)}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
        <div className={styles.heroStatus}>
          <div className={styles.statusLine}>
            {isBusy ? <LoaderCircle size={14} className={styles.spinningIcon} /> : topCandidate ? <Check size={14} className={styles.successIcon} /> : <AlertCircle size={14} className={styles.idleIcon} />}
            <AnimatePresence mode="popLayout">
              <motion.span key={statusDetail} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                {statusDetail}
              </motion.span>
            </AnimatePresence>
          </div>
          <div className={styles.heroBadgeRow}>
            <span className={`${styles.statusChip} ${styles[`statusChip${jobBadge.tone[0].toUpperCase()}${jobBadge.tone.slice(1)}`]}`}>
              {isBusy ? <LoaderCircle size={12} className={styles.spinningIcon} /> : jobBadge.tone === 'success' ? <Check size={12} className={styles.successIcon} /> : <AlertCircle size={12} className={styles.idleIcon} />}
              {jobBadge.label}
            </span>
            {reviewBadge && (
              <span className={`${styles.statusChip} ${styles[`statusChip${reviewBadge.tone[0].toUpperCase()}${reviewBadge.tone.slice(1)}`]}`}>
                {reviewBadge.label}
              </span>
            )}
            {isBusy && jobTiming.stageElapsedMs !== null && (
              <span className={styles.counterChip}>Stage {formatJobTiming(jobTiming.stageElapsedMs)}</span>
            )}
            {jobTiming.totalElapsedMs !== null && (
              <span className={styles.counterChip}>Total {formatJobTiming(jobTiming.totalElapsedMs)}</span>
            )}
            {lprState.job.trackingTier && (
              <span className={styles.counterChip}>
                {lprState.job.trackingTier}
                {typeof lprState.job.coverageRatio === 'number' ? ` ${Math.round(lprState.job.coverageRatio * 100)}%` : ''}
              </span>
            )}
            {lprState.targetTracks.length > 0 && (
              <span className={styles.counterChip}>
                <Target size={12} />
                {lprState.targetTracks.length}
              </span>
            )}
            {evidenceCount > 0 && (
              <span className={styles.counterChip}>
                <Image size={12} />
                {evidenceCount}
              </span>
            )}
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
          {isBusy && (
            <motion.button whileTap={{ scale: 0.95 }} type="button" className={styles.actionBtnUtility} onClick={() => void sendAction({ type: 'cancel-job' })} title="Cancel Current LPR Job">
              <X size={15} />
            </motion.button>
          )}
          <motion.button whileTap={{ scale: 0.95 }} type="button" className={`${styles.actionBtnUtility} ${lprState.useDenseSampling ? styles.utilityActive : ''}`} onClick={() => void sendAction({ type: 'toggle-dense-sampling' })} title="Dense Sampling">
            <Database size={15} />
          </motion.button>
          <motion.button whileTap={{ scale: 0.95 }} type="button" className={`${styles.actionBtnUtility} ${lprState.showDeveloperDiagnostics ? styles.utilityActive : ''}`} onClick={() => void sendAction({ type: 'toggle-developer-diagnostics' })} title="Diagnostics">
            <Zap size={15} />
          </motion.button>
          <motion.button whileTap={{ scale: 0.95 }} type="button" className={styles.actionBtnUtility} onClick={() => void sendAction({ type: 'export-evidence' })} disabled={!topCandidate && lprState.samples.length === 0} title="Export Evidence">
            <FileOutput size={15} />
          </motion.button>
          <motion.button whileTap={{ scale: 0.95 }} type="button" className={styles.actionBtnUtility} onClick={() => void sendAction({ type: 'clear-results' })} disabled={lprState.candidates.length === 0 && lprState.targetTracks.length === 0 && !lprState.analysisTrack && lprState.samples.length === 0} title="Reset Results">
            <RotateCcw size={15} />
          </motion.button>
        </div>
      </section>

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
        <div className={styles.profileSelectGroup}>
          <Select
            size="compact"
            ariaLabel="Analysis profile"
            value={lprState.selectedAnalysisProfileId}
            onChange={(analysisProfileId: string) => void sendAction({ type: 'set-analysis-profile', analysisProfileId })}
            options={analysisProfiles.map((profile: any) => ({
              value: profile.id,
              label: profile.label,
              description: compactProfileDescription(profile.id, profile.description),
            }))}
          />
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
    </>
  );
};

