import React from 'react';
import { listen } from '@tauri-apps/api/event';
import { convertFileSrc } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { save } from '@tauri-apps/plugin-dialog';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertCircle,
  Brain,
  Car,
  Clock,
  Download,
  Film,
  Image as ImageIcon,
  LocateFixed,
  RotateCcw,
  StopCircle,
  X,
  Crosshair,
} from 'lucide-react';
import { requestAiPanelWindowSession, saveGeneratedMediaAsset, sendAiPanelAction } from '../infrastructure/aiPanelApi';
import {
  AI_PANEL_SESSION_UPDATED_EVENT,
  type RevisionedAiPanelSessionSnapshot,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';
import { buildJobTimingSnapshot, formatElapsedDuration } from '../application/jobTiming';
import { buildDefaultAiEvidenceState } from '../domain/aiEvidenceState';
import { formatRulerLabel, formatTransportTime } from '../domain/model';
import { shouldApplyRevisionedWindowSnapshot, unwrapRevisionedWindowSnapshot } from '../../../vnext/windowing/revisionedSnapshot';
import styles from './AiEvidenceWindow.module.css';

function clamp01(value: number | null | undefined) {
  return Math.max(0, Math.min(1, value ?? 0));
}

function toLocalAsset(path: string | null | undefined) {
  return path ? convertFileSrc(path) : null;
}

function downloadName(path: string | null | undefined, fallback: string) {
  if (!path) return fallback;
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? fallback;
}

function compactLabel(value: string | null | undefined, fallback: string) {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

function formatProgressCounter(prefix: string, index: number | null | undefined, count: number | null | undefined) {
  if (index === null || index === undefined || count === null || count === undefined || count <= 0) {
    return null;
  }
  return `${prefix} ${index}/${count}`;
}

export const AiEvidenceWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<AiPanelSessionSnapshot | null>(null);
  const [promptDraft, setPromptDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [isFocused, setIsFocused] = React.useState(false);
  const [clockNowMs, setClockNowMs] = React.useState(() => Date.now());
  const latestRevisionRef = React.useRef(0);

  const aiState = snapshot?.ai ?? buildDefaultAiEvidenceState();
  const result = aiState.result;
  const keyframes = result?.keyframes ?? [];
  const runtimeReady = snapshot?.runtimeStatus?.available ?? false;
  const isRunning = aiState.job.status === 'queued' || aiState.job.status === 'running';
  const progress = clamp01(aiState.job.progress);
  const hasError = Boolean(errorMessage || aiState.job.error);
  const canRun = Boolean(snapshot?.hasActiveFile) && runtimeReady && !isRunning;
  const canReset = !isRunning && (Boolean(aiState.prompt.trim()) || Boolean(result));
  const jobTiming = React.useMemo(() => buildJobTimingSnapshot(aiState.job, clockNowMs), [aiState.job, clockNowMs]);
  const stageElapsedLabel = formatElapsedDuration(jobTiming.stageElapsedMs);
  const totalElapsedLabel = formatElapsedDuration(jobTiming.totalElapsedMs);
  const workflowStepLabel = formatProgressCounter('Step', aiState.job.stepIndex, aiState.job.stepCount);
  const stageStepLabel = aiState.job.stageStepCount && aiState.job.stageStepCount > 1
    ? formatProgressCounter('Stage', aiState.job.stageStepIndex, aiState.job.stageStepCount)
    : null;
  const currentToolLabel = compactLabel(aiState.job.toolLabel ?? aiState.job.toolName, '');

  const statusMessage = compactLabel(
    aiState.job.error || errorMessage || result?.summary || aiState.job.detail,
    ''
  );

  React.useEffect(() => {
    let disposed = false;
    let removeSessionListener: (() => void) | undefined;

    void listen<AiPanelSessionSnapshot | RevisionedAiPanelSessionSnapshot>(AI_PANEL_SESSION_UPDATED_EVENT, (event) => {
      if (disposed) return;
      const envelope = unwrapRevisionedWindowSnapshot(event.payload);
      if (!shouldApplyRevisionedWindowSnapshot(latestRevisionRef.current, envelope.revision)) {
        return;
      }
      latestRevisionRef.current = envelope.revision;
      setSnapshot(envelope.snapshot);
      setErrorMessage(null);
    }).then((unlisten) => {
      removeSessionListener = unlisten;
    });

    void requestAiPanelWindowSession().catch((error) => {
      if (disposed) return;
      setErrorMessage(error instanceof Error ? error.message : 'Unable to request the latest AI panel session.');
    });

    return () => {
      disposed = true;
      removeSessionListener?.();
    };
  }, []);

  React.useEffect(() => {
    let intervalId: ReturnType<typeof setInterval>;
    if (isRunning) {
      intervalId = setInterval(() => {
        setClockNowMs(Date.now());
      }, 200);
    } else {
      setClockNowMs(Date.now());
    }
    return () => clearInterval(intervalId);
  }, [isRunning, aiState.job.startedAt, aiState.job.updatedAt]);

  React.useEffect(() => {
    setPromptDraft(snapshot?.ai.prompt ?? '');
  }, [snapshot?.ai.prompt, snapshot?.activeFileName]);

  const runPanelAction = React.useCallback(async (action: AiPanelAction) => {
    try {
      setErrorMessage(null);
      await sendAiPanelAction(action);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Unable to send the latest AI panel action.');
    }
  }, []);

  const handleSaveGeneratedAsset = React.useCallback(async (
    sourcePath: string | null | undefined,
    fallbackName: string,
    filterName: string,
  ) => {
    if (!sourcePath) {
      return;
    }

    const suggestedName = downloadName(sourcePath, fallbackName);
    const extension = suggestedName.split('.').at(-1)?.toLowerCase() || fallbackName.split('.').at(-1)?.toLowerCase() || 'bin';
    const selectedPath = await save({
      title: 'Save generated media asset',
      defaultPath: suggestedName,
      filters: [{ name: filterName, extensions: [extension] }],
    });

    if (!selectedPath) {
      return;
    }

    const normalizedPath = selectedPath.toLowerCase().endsWith(`.${extension}`)
      ? selectedPath
      : `${selectedPath}.${extension}`;

    try {
      setErrorMessage(null);
      await saveGeneratedMediaAsset(sourcePath, normalizedPath);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Unable to save the generated media asset.');
    }
  }, []);

  const handleRun = async () => {
    const prompt = promptDraft.trim();
    if (!prompt) {
      setErrorMessage('請輸入描述。');
      return;
    }
    await runPanelAction({ type: 'run-analysis', prompt });
  };

  const handleClose = async () => {
    await getCurrentWindow().close();
  };

  return (
    <div className={styles.window}>
      <div data-tauri-drag-region className={styles.chrome}>
        <div className={styles.chromeMeta} data-tauri-drag-region>
          <span className={styles.chromeIcon}><Brain size={14} /></span>
          <span className={styles.chromeTitle}>AI Evidence</span>
        </div>
        <div className={styles.chromeActions}>
          <button type="button" className={styles.chromeButton} onClick={() => void handleClose()} aria-label="Close AI panel">
            <X size={14} />
          </button>
        </div>
      </div>

      <div className={styles.body}>
        {!snapshot?.hasActiveFile ? (
          <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className={styles.emptyState}>
            <div className={styles.emptyStateIcon}><Film size={28} /></div>
            <p>Import a file to start analysis.</p>
          </motion.div>
        ) : (
          <>
            <motion.section layout className={`${styles.composer} ${isFocused ? styles.composerFocus : ''}`}>
              <textarea
                className={styles.textarea}
                value={promptDraft}
                onChange={(event) => setPromptDraft(event.target.value)}
                onFocus={() => setIsFocused(true)}
                onBlur={() => setIsFocused(false)}
                placeholder="例如：NCE9762 車牌的駕駛在路口右轉"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void handleRun();
                  }
                }}
              />
              <div className={styles.composerToolbar}>
                <div className={styles.composerStatus}>
                  <div className={`${styles.statusDot} ${hasError ? styles.statusDotError : isRunning ? styles.statusDotRunning : runtimeReady ? styles.statusDotReady : ''}`} title={runtimeReady ? 'Engine Ready' : 'Engine Offline'} />
                  {runtimeReady ? 'Engine Ready' : 'Engine Offline'}
                </div>
                <div className={styles.composerActions}>
                  {canReset && (
                    <button type="button" className={styles.actionBtn} onClick={() => void runPanelAction({ type: 'reset-session' })}>
                      <RotateCcw size={14} /> Reset
                    </button>
                  )}
                  {isRunning ? (
                    <button type="button" className={styles.actionBtn} onClick={() => void runPanelAction({ type: 'cancel-job' })}>
                      <StopCircle size={14} /> Cancel
                    </button>
                  ) : (
                    <button type="button" className={styles.runBtn} onClick={() => void handleRun()} disabled={!canRun}>
                      <Brain size={14} /> Run AI Evidence
                    </button>
                  )}
                </div>
              </div>
            </motion.section>

            <AnimatePresence mode="popLayout">
              {hasError && statusMessage && (
                <motion.div layout initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className={styles.errorBanner}>
                  <AlertCircle size={14} /> {statusMessage}
                </motion.div>
              )}

              {/* Phase 1: Idle (No Result, Not Running) */}
              {!result && !isRunning && (
                <motion.div key="awaiting" layout initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className={styles.awaitingState}>
                  <Brain size={48} className={styles.awaitingIcon} />
                  <span className={styles.awaitingText}>Describe an event to find evidence.</span>
                </motion.div>
              )}

              {/* Phase 2: Running */}
              {isRunning && (
                <motion.div key="running" layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className={styles.progressSection}>
                  <div className={styles.progressHeader}>
                    <div className={styles.progressStatusBlock}>
                      <div className={styles.progressStatusRow}>
                        <Brain size={14} className={styles.spinningIcon} />
                        <span className={styles.progressStatusText}>{statusMessage || 'Analyzing...'}</span>
                        {workflowStepLabel && <span className={styles.progressMetaPill}>{workflowStepLabel}</span>}
                        {stageStepLabel && <span className={styles.progressMetaPill}>{stageStepLabel}</span>}
                        {currentToolLabel && <span className={styles.progressMetaPill}>{currentToolLabel}</span>}
                        {jobTiming.stageElapsedMs !== null && (
                          <span className={styles.elapsedTimer}>Stage {stageElapsedLabel}</span>
                        )}
                        {jobTiming.totalElapsedMs !== null && (
                          <span className={styles.elapsedTimer}>Total {totalElapsedLabel}</span>
                        )}
                      </div>
                    </div>
                    <span className={styles.progressPercent}>{Math.round(progress * 100)}%</span>
                  </div>
                  <div className={styles.progressTrack}>
                    <div className={styles.progressFill} style={{ width: `${Math.round(progress * 100)}%` }} />
                  </div>
                </motion.div>
              )}

              {/* Phase 3: Completed / Result */}
              {result && !isRunning && (
                <motion.div key="results" layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className={styles.resultsArea}>

                  <div className={styles.metricsRow}>
                    {result.plateNumber && (
                      <div className={styles.metricPill}>
                        <Car size={14} className={styles.metricIcon} />
                        <span className={styles.metricValue}>{result.plateNumber}</span>
                      </div>
                    )}
                    {result.primaryAnchor && (
                      <button className={styles.metricPill} onClick={() => void runPanelAction({ type: 'seek-to-time', timeMs: result.primaryAnchor!.timeMs })}>
                        <Crosshair size={14} className={styles.metricIcon} />
                        <span className={styles.metricValue}>{formatRulerLabel(result.primaryAnchor.timeMs)}</span>
                      </button>
                    )}
                    {result.interval && (
                      <button className={styles.metricPill} onClick={() => void runPanelAction({ type: 'seek-to-time', timeMs: result.interval!.startMs })}>
                        <Clock size={14} className={styles.metricIcon} />
                        <span className={styles.metricValue}>{formatTransportTime(result.interval.startMs)} - {formatTransportTime(result.interval.endMs)}</span>
                      </button>
                    )}
                    {result.clipPath && (
                      <button
                        type="button"
                        className={styles.metricPill}
                        onClick={() => void handleSaveGeneratedAsset(result.clipPath, 'ai-evidence-clip.mp4', 'MP4 Video')}
                      >
                        <Download size={14} className={styles.metricIcon} />
                        <span className={styles.metricValue}>Clip</span>
                      </button>
                    )}
                  </div>
                  
                  {result.summary && (
                    <div className={styles.resultSummary}>
                      <p>{result.summary}</p>
                    </div>
                  )}

                  {keyframes.length > 0 && (
                    <div className={styles.framesGrid}>
                      {keyframes.map((keyframe, i) => {
                        const imageHref = toLocalAsset(keyframe.frame.imagePath);
                        return (
                          <motion.article
                            key={keyframe.frame.frameId}
                            className={styles.frameCard}
                            initial={{ opacity: 0, scale: 0.9 }}
                            animate={{ opacity: 1, scale: 1 }}
                            transition={{ delay: i * 0.05 }}
                          >
                            {imageHref ? (
                              <img className={styles.frameImg} src={imageHref} alt={keyframe.description || keyframe.frame.label} />
                            ) : (
                              <div className={styles.frameFallback}><ImageIcon size={24} /></div>
                            )}

                            <div className={styles.frameOverlay}>
                              <div className={styles.frameHeader}>
                                <span className={styles.frameTime}>{formatRulerLabel(keyframe.frame.timeMs)}</span>
                                <div className={styles.frameActions}>
                                  <button
                                    type="button"
                                    className={styles.frameActionBtn}
                                    onClick={() => void runPanelAction({ type: 'seek-to-time', timeMs: keyframe.frame.timeMs })}
                                    title="Locate"
                                  >
                                    <LocateFixed size={13} />
                                  </button>
                                  {keyframe.frame.imagePath && (
                                    <button
                                      type="button"
                                      className={styles.frameActionBtn}
                                      onClick={() => void handleSaveGeneratedAsset(
                                        keyframe.frame.imagePath,
                                        `${keyframe.frame.frameId}.png`,
                                        'PNG Image',
                                      )}
                                      title="Save"
                                    >
                                      <Download size={13} />
                                    </button>
                                  )}
                                </div>
                              </div>
                              <p className={styles.frameDesc}>{compactLabel(keyframe.description, 'Key frame description unavailable.')}</p>
                            </div>
                          </motion.article>
                        );
                      })}
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </>
        )}
      </div>
    </div>
  );
};