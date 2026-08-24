// @ts-nocheck
import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Clock, LocateFixed, Search, LayoutTemplate, Database, AlertCircle, FileOutput, ArrowDownToLine, Zap, Image, Maximize2, Minimize2, MousePointer2 } from 'lucide-react';
import styles from './LprWindow.module.css';

export const formatConfidence = (c) => Math.round(c * 100) + '%';

export const LprDataViewer = ({
  activeTab, setActiveTab, lprState, sendAction, evidenceSamples, tabContentVariants, listItemVariants, buildTargetDiagnosticsLines,
  candidateBadgeLabel, candidateSelection, evidenceCandidates, toImageSrc, qualityMetrics, formatMetric,
  samplePrimaryText, sampleReasonTokens, formatSampleTimestamp, activeEvidenceSample, handleSeekToSample, formatHistoryLabel,
  currentPlayheadMs
}) => {
  return (
<section className={styles.dataViewer}>
              <div className={styles.tabHeader}>
                <button type="button" className={`${styles.tabBtn} ${activeTab === 'targets' ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab('targets')}>
                  Targets {lprState.targetTracks.length > 0 && <span className={styles.tabCount}>{lprState.targetTracks.length}</span>}
                  {activeTab === 'targets' && <motion.div layoutId="activeTabIndicator" className={styles.activeTabIndicator} />}
                </button>
                <button type="button" className={`${styles.tabBtn} ${activeTab === 'candidates' ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab('candidates')}>
                  Candidates {lprState.candidates.length > 0 && <span className={styles.tabCount}>{lprState.candidates.length}</span>}
                  {activeTab === 'candidates' && <motion.div layoutId="activeTabIndicator" className={styles.activeTabIndicator} />}
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
                  {/* TARGETS TAB */}
                  {activeTab === 'targets' && (
                    <motion.div key="targets" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.listContainer}>
                      {lprState.targetTracks.length === 0 && <div className={styles.emptyInline}>No targets</div>}
                      {lprState.targetTracks.map((track) => {
                        const displayTrack = lprState.analysisTrack?.id === track.id ? lprState.analysisTrack : track;
                        const diagnosticLines = lprState.showDeveloperDiagnostics ? buildTargetDiagnosticsLines(displayTrack) : [];
                        return (
                        <motion.button
                          layout
                          variants={listItemVariants}
                          key={track.id}
                          type="button"
                          className={`${styles.targetRowBtn} ${track.id === lprState.selectedTargetTrackId ? styles.targetRowBtnActive : ''}`}
                          onClick={() => void sendAction({
                            type: 'select-target-track',
                            targetTrackId: track.id,
                            anchorTimeMs: track.frames[0]?.timeMs ?? snapshot.anchorTimeMs,
                          })}
                        >
                          <div className={styles.targetRowContent}>
                            <div className={styles.targetRowHeader}>
                              <span className={styles.targetRowTitle}>{track.label}</span>
                              <span className={styles.targetRowConfidence}>{formatConfidence(track.confidence)}</span>
                            </div>
                            <span className={styles.targetRowFrame}>
                              Frame {formatSampleTimestamp(track.frames[0]?.timeMs ?? snapshot.anchorTimeMs)}
                            </span>
                            {diagnosticLines.map((line) => (
                              <span key={`${track.id}-${line}`} className={styles.targetRowMeta}>{line}</span>
                            ))}
                          </div>
                          {track.id === lprState.selectedTargetTrackId && <motion.div layoutId="activeTarget" className={styles.activeListItemGlow} />}
                        </motion.button>
                        );
                      })}
                    </motion.div>
                  )}

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
                    </motion.div>
                  )}

                  {activeTab === 'evidence' && (
                    <motion.div key="evidence" variants={tabContentVariants} initial="hidden" animate="show" exit="exit" className={styles.listContainer}>
                      {evidenceSamples.length === 0 && <div className={styles.emptyInline}>No evidence</div>}
                      {evidenceSamples.map((entry) => {
                        const isActive = entry.sample.id === activeEvidenceSample?.sample.id;
                        const reasonTokens = sampleReasonTokens(entry.sample);
                        return (
                          <motion.div
                            layout
                            variants={listItemVariants}
                            key={entry.sample.id}
                            className={`${styles.evidenceListItem} ${isActive ? styles.evidenceListItemActive : ''}`}
                          >
                            <div className={styles.evidenceListHeader}>
                              <button
                                type="button"
                                className={styles.evidenceRowContentBtn}
                                onClick={() => {
                                  setSelectedEvidenceSampleId(entry.sample.id);
                                  setIsEvidenceSelectionPinned(true);
                                }}
                              >
                                <span className={styles.evidenceChipTime}>{formatSampleTimestamp(entry.sample.timeMs)}</span>
                                <div className={styles.evidencePlateRow}>
                                  <strong className={styles.evidenceChipText}>{entry.matchingCandidate?.text ?? samplePrimaryText(entry.sample)}</strong>
                                  <span className={styles.evidenceChipBadge}>{formatConfidence(entry.sample.quality?.overallScore ?? 0)}</span>
                                </div>
                                {reasonTokens.length > 0 && (
                                  <div className={styles.evidenceReasonRow}>
                                    {reasonTokens.map((reason: any) => (
                                      <span key={`${entry.sample.id}-${reason}`} className={styles.evidenceReasonChip}>{reason}</span>
                                    ))}
                                  </div>
                                )}
                              </button>
                              
                              <button
                                type="button"
                                className={styles.evidenceJumpIconBtn}
                                onClick={() => void handleSeekToSample(entry.sample.id, entry.sample.timeMs)}
                                title="Jump to this frame"
                              >
                                <LocateFixed size={14} />
                              </button>
                            </div>

                            {isActive && (
                              <div className={styles.evidenceExpanded}>
                                <div className={styles.evidencePreviewGrid}>
                                  {entry.artifacts.map((artifact) => {
                                    const isOcrInputArtifact = artifact.key === entry.sample.ocrInput?.stage || (artifact.key === 'working' && entry.sample.ocrInput?.stage === 'working');
                                    return (
                                    <div key={artifact.key} className={`${styles.evidencePreviewCard} ${isOcrInputArtifact ? styles.evidencePreviewCardActive : ''}`}>
                                      <div className={styles.evidencePreviewLabel}><Image size={12} className={styles.mutedIcon} /> {artifact.label}</div>
                                      {isOcrInputArtifact && <span className={styles.evidencePreviewInputBadge}>OCR</span>}
                                      <img className={styles.evidencePreviewImage} src={toImageSrc(artifact.path)} alt={`${artifact.label} ${formatSampleTimestamp(entry.sample.timeMs)}`} />
                                    </div>
                                  );})}
                                </div>

                                <div className={styles.evidenceMetaRail}>
                                  <div className={styles.evidenceMetaSection}>
                                    <div className={styles.evidenceMetaHeader}>
                                      <Zap size={14} className={styles.metaIcon} />
                                      <span className={styles.evidenceMetaTitle}>Image Quality</span>
                                    </div>
                                    <div className={styles.evidenceMetricList}>
                                      {qualityMetrics(entry.sample).map(([label, value]) => {
                                        const percent = formatMetric(value);
                                        return (
                                          <div key={label} className={styles.evidenceMetricRow}>
                                            <div className={styles.metricHeader}>
                                              <span className={styles.metricLabel}>{label}</span>
                                              <strong className={styles.metricValue}>{percent}</strong>
                                            </div>
                                            <div className={styles.metricTrack}>
                                              <div className={styles.metricFill} style={{ width: percent }} />
                                            </div>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </div>
                                  
                                  {entry.sample.candidates.length > 0 && (
                                    <div className={styles.evidenceMetaSection}>
                                      <div className={styles.evidenceMetaHeader}>
                                        <Database size={14} className={styles.metaIcon} />
                                        <span className={styles.evidenceMetaTitle}>Candidates</span>
                                      </div>
                                      <div className={styles.evidenceCandidateList}>
                                        {evidenceCandidates(entry.sample).map((candidate: any, idx: number) => {
                                          const isTop = idx === 0;
                                          const percent = formatConfidence(candidate.confidence);
                                          return (
                                            <div key={candidate.id} className={`${styles.evidenceCandidateRow} ${isTop ? styles.candidateRowTop : ''}`}>
                                              <div className={styles.candidateHeader}>
                                                <span className={styles.candidateRank}>#{idx + 1}</span>
                                                <span className={styles.candidateText}>{candidate.text}</span>
                                                <strong className={styles.candidateScore}>{percent}</strong>
                                              </div>
                                              <div className={styles.metricTrack}>
                                                <div className={`${styles.metricFill} ${isTop ? styles.metricFillTop : ''}`} style={{ width: percent }} />
                                              </div>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}
                          </motion.div>
                        );
                      })}
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
                          <span className={styles.infoItemPill}>{formatHistoryLabel(entry.interval, entry.analysisProfileId, entry.developerDiagnosticsEnabled)}</span>
                        </motion.div>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </section>
  );
};

