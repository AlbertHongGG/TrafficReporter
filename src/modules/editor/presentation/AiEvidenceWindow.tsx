import React from 'react';
import { listen } from '@tauri-apps/api/event';
import { convertFileSrc } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import {
  AlertCircle,
  Brain,
  Download,
  Film,
  LoaderCircle,
  LocateFixed,
  PlayCircle,
  RotateCcw,
  Shield,
  X,
} from 'lucide-react';
import { requestAiPanelWindowSession, sendAiPanelAction } from '../infrastructure/aiPanelApi';
import {
  AI_PANEL_SESSION_UPDATED_EVENT,
  type AiPanelAction,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';
import { buildDefaultAiEvidenceState } from '../domain/aiEvidenceState';
import { formatRulerLabel, formatTransportTime } from '../domain/model';
import styles from './AiEvidenceWindow.module.css';

function clamp01(value: number | null | undefined) {
  return Math.max(0, Math.min(1, value ?? 0));
}

function toLocalAsset(path: string | null | undefined) {
  return path ? convertFileSrc(path) : null;
}

function downloadName(path: string | null | undefined, fallback: string) {
  if (!path) {
    return fallback;
  }
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? fallback;
}

function compactLabel(value: string | null | undefined, fallback: string) {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

function humanizeToken(value: string | null | undefined, fallback: string) {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replace(/[_-]+/g, ' ') : fallback;
}

function buildStatusLabel(
  status: string | null | undefined,
  runtimeReady: boolean,
  hasResult: boolean,
) {
  switch (status) {
    case 'queued':
    case 'running':
      return 'Running';
    case 'failed':
      return 'Failed';
    case 'completed':
      return 'Done';
    case 'cancelled':
      return 'Stopped';
    default:
      if (!runtimeReady) {
        return 'Offline';
      }
      return hasResult ? 'Ready' : 'Idle';
  }
}

export const AiEvidenceWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<AiPanelSessionSnapshot | null>(null);
  const [promptDraft, setPromptDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  const aiState = snapshot?.ai ?? buildDefaultAiEvidenceState();
  const result = aiState.result;
  const keyframes = result?.keyframes ?? [];
  const runtimeReady = snapshot?.runtimeStatus?.available ?? false;
  const isRunning = aiState.job.status === 'queued' || aiState.job.status === 'running';
  const clipHref = toLocalAsset(result?.clipPath);
  const progress = clamp01(aiState.job.progress);
  const hasError = Boolean(errorMessage || aiState.job.error);
  const canRun = Boolean(snapshot?.hasActiveFile) && runtimeReady && !isRunning;
  const canReset = !isRunning && (Boolean(aiState.prompt.trim()) || Boolean(result));
  const statusLabel = buildStatusLabel(aiState.job.status, runtimeReady, Boolean(result));
  const statusMessage = compactLabel(
    aiState.job.error || errorMessage || result?.summary || aiState.job.detail,
    runtimeReady ? 'Ready for analysis.' : 'Local engine offline.',
  );
  const intervalLabel = result?.interval
    ? `${formatTransportTime(result.interval.startMs)} - ${formatTransportTime(result.interval.endMs)}`
    : 'No clip yet';
  const anchorLabel = result?.primaryAnchor ? formatRulerLabel(result.primaryAnchor.timeMs) : 'No anchor';
  const reviewLabel = humanizeToken(result?.projection.review?.status, 'idle');

  React.useEffect(() => {
    let disposed = false;
    let removeSessionListener: (() => void) | undefined;

    void listen<AiPanelSessionSnapshot>(AI_PANEL_SESSION_UPDATED_EVENT, (event) => {
      if (disposed) {
        return;
      }
      setSnapshot(event.payload);
      setErrorMessage(null);
    }).then((unlisten) => {
      removeSessionListener = unlisten;
    });

    void requestAiPanelWindowSession().catch((error) => {
      if (disposed) {
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : 'Unable to request the latest AI panel session.');
    });

    return () => {
      disposed = true;
      removeSessionListener?.();
    };
  }, []);

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
          <div className={styles.emptyState}>
            <div className={styles.emptyStateIcon}><Film size={28} /></div>
            <p>Import a file to start analysis.</p>
          </div>
        ) : (
          <>
            <section className={styles.composer}>
              <div className={styles.promptArea}>
                <textarea
                  className={styles.textarea}
                  value={promptDraft}
                  onChange={(event) => setPromptDraft(event.target.value)}
                  placeholder="例如：NCE9762 的駕駛在路口右轉"
                />
              </div>

              <div className={styles.commandColumn}>
                <button type="button" className={styles.actionPrimary} onClick={() => void handleRun()} disabled={!canRun}>
                  {isRunning ? <LoaderCircle size={16} className={styles.spinningIcon} /> : <PlayCircle size={16} />}
                  Run
                </button>
                <button type="button" className={styles.actionButton} onClick={() => void runPanelAction({ type: 'cancel-job' })} disabled={!isRunning}>
                  <X size={15} />
                  Cancel
                </button>
                <button type="button" className={styles.actionButton} onClick={() => void runPanelAction({ type: 'reset-session' })} disabled={!canReset}>
                  <RotateCcw size={15} />
                  Reset
                </button>
              </div>
            </section>

            <div className={styles.summaryGrid}>
              <section className={styles.card}>
                <div className={styles.cardHeader}>
                  <div className={styles.cardHeaderLeft}>
                    <span className={`${styles.statusBadge} ${runtimeReady ? styles.statusBadgeReady : styles.statusBadgeMuted}`}>{statusLabel}</span>
                    <span className={`${styles.runtimeBadge} ${runtimeReady ? styles.runtimeBadgeReady : ''}`}>{runtimeReady ? 'Local Engine' : 'Offline'}</span>
                  </div>
                  <strong className={styles.percentValue}>{Math.round(progress * 100)}%</strong>
                </div>

                <div className={styles.progressTrack}>
                  <div className={styles.progressValue} style={{ width: `${Math.round(progress * 100)}%` }} />
                </div>

                <div className={styles.metricGrid}>
                  <div className={styles.metricCard}>
                    <span>Plate</span>
                    <strong>{compactLabel(result?.plateNumber, '—')}</strong>
                  </div>
                  <div className={styles.metricCard}>
                    <span>Anchor</span>
                    <strong>{anchorLabel}</strong>
                  </div>
                  <div className={styles.metricCard}>
                    <span>Playhead</span>
                    <strong>{formatRulerLabel(snapshot?.playheadMs ?? 0)}</strong>
                  </div>
                </div>

                <div className={`${styles.messageRow} ${hasError ? styles.messageRowError : ''}`}>
                  {hasError ? <AlertCircle size={14} /> : isRunning ? <LoaderCircle size={14} className={styles.spinningIcon} /> : <Shield size={14} />}
                  <span>{statusMessage}</span>
                </div>
              </section>

              <section className={styles.card}>
                <div className={styles.cardHeader}>
                  <span className={styles.cardTitle}>Clip</span>
                  {clipHref && (
                    <a className={styles.inlineAction} href={clipHref} download={downloadName(result?.clipPath, 'ai-evidence-clip.mp4')}>
                      <Download size={14} />
                    </a>
                  )}
                </div>

                <div className={styles.clipStack}>
                  <button
                    type="button"
                    className={styles.seekRow}
                    onClick={() => result?.interval && void runPanelAction({ type: 'seek-to-time', timeMs: result.interval.startMs })}
                    disabled={!result?.interval}
                  >
                    <PlayCircle size={14} />
                    <span>{intervalLabel}</span>
                  </button>
                  <button
                    type="button"
                    className={styles.seekRow}
                    onClick={() => result?.primaryAnchor && void runPanelAction({ type: 'seek-to-time', timeMs: result.primaryAnchor.timeMs })}
                    disabled={!result?.primaryAnchor}
                  >
                    <LocateFixed size={14} />
                    <span>{anchorLabel}</span>
                  </button>
                </div>

                <div className={styles.clipMetaRow}>
                  <span className={styles.metaPill}>{reviewLabel}</span>
                  <span className={styles.metaPill}>{keyframes.length} frame(s)</span>
                </div>
              </section>
            </div>

            <section className={`${styles.card} ${styles.framesCard}`}>
              <div className={styles.cardHeader}>
                <span className={styles.cardTitle}>Frames</span>
                <span className={styles.countBadge}>{keyframes.length}</span>
              </div>

              {keyframes.length > 0 ? (
                <div className={styles.keyframeRail}>
                  {keyframes.map((keyframe) => {
                    const imageHref = toLocalAsset(keyframe.frame.imagePath);
                    return (
                      <article key={keyframe.frame.frameId} className={styles.keyframeCard}>
                        <div className={styles.keyframeMedia}>
                          {imageHref ? (
                            <img className={styles.keyframeImage} src={imageHref} alt={keyframe.description || keyframe.frame.label} />
                          ) : (
                            <div className={styles.keyframeFallback}><Film size={18} /></div>
                          )}
                        </div>

                        <div className={styles.keyframeBody}>
                          <strong className={styles.keyframeTime}>{formatRulerLabel(keyframe.frame.timeMs)}</strong>
                          <p className={styles.keyframeText}>{compactLabel(keyframe.description, keyframe.frame.label)}</p>
                          <div className={styles.keyframeActions}>
                            <button
                              type="button"
                              className={styles.inlineButton}
                              onClick={() => void runPanelAction({ type: 'seek-to-time', timeMs: keyframe.frame.timeMs })}
                            >
                              <LocateFixed size={13} />
                              Locate
                            </button>
                            {imageHref && (
                              <a
                                className={styles.inlineButton}
                                href={imageHref}
                                download={downloadName(keyframe.frame.imagePath, `${keyframe.frame.frameId}.jpg`)}
                              >
                                <Download size={13} />
                                Save
                              </a>
                            )}
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className={styles.framesEmpty}>Awaiting evidence</div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
};