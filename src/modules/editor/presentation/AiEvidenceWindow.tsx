import React from 'react';
import { listen } from '@tauri-apps/api/event';
import { convertFileSrc } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { Brain, Clock3, Download, LoaderCircle, LocateFixed, PlayCircle, Shield, X } from 'lucide-react';
import { requestAiPanelWindowSession, sendAiPanelAction } from '../infrastructure/aiPanelApi';
import {
  AI_PANEL_SESSION_UPDATED_EVENT,
  type AiPanelSessionSnapshot,
} from '../application/aiPanelWindow';
import { buildDefaultAiEvidenceState } from '../domain/aiEvidenceState';
import { formatRulerLabel, formatTransportTime } from '../domain/model';
import styles from './AiEvidenceWindow.module.css';

function toLocalAsset(path: string | null | undefined) {
  return path ? convertFileSrc(path) : null;
}

function downloadName(path: string | null | undefined, fallback: string) {
  if (!path) {
    return fallback;
  }
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? fallback;
}

export const AiEvidenceWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<AiPanelSessionSnapshot | null>(null);
  const [promptDraft, setPromptDraft] = React.useState('');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  const aiState = snapshot?.ai ?? buildDefaultAiEvidenceState();
  const result = aiState.result;
  const runtimeReady = snapshot?.runtimeStatus?.available ?? false;
  const isRunning = aiState.job.status === 'queued' || aiState.job.status === 'running';
  const clipHref = toLocalAsset(result?.clipPath);

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

  const handleRun = async () => {
    const prompt = promptDraft.trim();
    if (!prompt) {
      setErrorMessage('請先輸入自然語言描述。');
      return;
    }
    setErrorMessage(null);
    await sendAiPanelAction({ type: 'run-analysis', prompt });
  };

  const handleClose = async () => {
    await getCurrentWindow().close();
  };

  const handleSeek = async (timeMs: number) => {
    await sendAiPanelAction({ type: 'seek-to-time', timeMs });
  };

  const plateStatus = result?.projection.review?.status ?? 'idle';

  return (
    <div className={styles.window}>
      <header className={styles.chrome} data-tauri-drag-region>
        <div className={styles.chromeMeta}>
          <span className={styles.chromeTitle}>AI Evidence</span>
          <span className={`${styles.runtimeBadge} ${runtimeReady ? styles.runtimeReady : ''}`}>
            {runtimeReady ? 'Runtime Ready' : 'Runtime Missing'}
          </span>
        </div>
        <button type="button" className={styles.chromeButton} onClick={() => void handleClose()} aria-label="Close AI panel">
          <X size={16} />
        </button>
      </header>

      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <section className={styles.section}>
            <div className={styles.label}>輸入描述</div>
            <div className={styles.hint}>
              請務必描述目標車輛外觀或車牌，以及目標行為/違規事項。
            </div>
            <textarea
              className={styles.textarea}
              value={promptDraft}
              onChange={(event) => setPromptDraft(event.target.value)}
              placeholder="例如：車牌號碼 BNY-7958 的機車有紅燈右轉的違規事項"
            />
            <div className={styles.buttonRow}>
              <button type="button" className={styles.primaryButton} onClick={() => void handleRun()} disabled={!snapshot?.hasActiveFile || isRunning}>
                {isRunning ? <LoaderCircle size={16} className="spin" /> : <Brain size={16} />}
                {isRunning ? '分析中' : '執行'}
              </button>
              <button type="button" className={styles.secondaryButton} onClick={() => void sendAiPanelAction({ type: 'cancel-job' })} disabled={!isRunning}>
                取消
              </button>
              <button type="button" className={styles.ghostButton} onClick={() => void sendAiPanelAction({ type: 'reset-session' })} disabled={isRunning}>
                清除
              </button>
            </div>
          </section>

          <section className={styles.statusCard}>
            <div className={styles.statusHeader}>
              <div className={styles.statusTitle}>
                <LoaderCircle size={16} />
                執行狀態
              </div>
              <div>{Math.round((aiState.job.progress ?? 0) * 100)}%</div>
            </div>
            <div className={styles.statusText}>{aiState.job.stage || 'Idle'}</div>
            <div className={styles.statusText}>{aiState.job.detail || '等待執行。'}</div>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${Math.max(0, Math.min(100, (aiState.job.progress ?? 0) * 100))}%` }} />
            </div>
            {errorMessage && <div className={styles.statusText}>{errorMessage}</div>}
            {aiState.job.error && <div className={styles.statusText}>{aiState.job.error}</div>}
          </section>

          <section className={styles.summaryCard}>
            <div className={styles.summaryHeader}>
              <div className={styles.summaryTitle}>
                <Shield size={16} />
                結果摘要
              </div>
            </div>
            <div className={styles.metaGrid}>
              <div className={styles.metaItem}>
                <div className={styles.metaKey}>目前影片</div>
                <div className={styles.metaValue}>{snapshot?.activeFileName ?? '--'}</div>
              </div>
              <div className={styles.metaItem}>
                <div className={styles.metaKey}>車牌號碼</div>
                <div className={styles.metaValue}>{result?.plateNumber ?? '--'}</div>
              </div>
              <div className={styles.metaItem}>
                <div className={styles.metaKey}>完整區段</div>
                <div className={styles.metaValue}>
                  {result?.interval ? `${formatRulerLabel(result.interval.startMs)} - ${formatRulerLabel(result.interval.endMs)}` : '--'}
                </div>
              </div>
              <div className={styles.metaItem}>
                <div className={styles.metaKey}>Review 狀態</div>
                <div className={styles.metaValue}>{plateStatus}</div>
              </div>
            </div>
            <div className={styles.summaryText}>{result?.summary ?? '尚未產生 AI evidence 結果。'}</div>
          </section>
        </aside>

        <main className={styles.content}>
          <section className={styles.clipCard}>
            <div className={styles.clipHeader}>
              <div className={styles.clipTitle}>
                <PlayCircle size={16} />
                事件片段
              </div>
              {clipHref && (
                <a className={styles.downloadButton} href={clipHref} download={downloadName(result?.clipPath, 'ai-evidence-clip.mp4')}>
                  <Download size={14} />
                  下載片段
                </a>
              )}
            </div>
            <div className={styles.clipText}>
              {result?.interval
                ? `影片時間：${formatTransportTime(result.interval.startMs)} - ${formatTransportTime(result.interval.endMs)}`
                : '尚未產生事件片段。'}
            </div>
            {result?.primaryAnchor && (
              <div className={styles.clipText}>
                Anchor：{result.primaryAnchor.label} ({formatRulerLabel(result.primaryAnchor.timeMs)})
              </div>
            )}
          </section>

          <section className={styles.section}>
            <div className={styles.label}>關鍵幀</div>
            {result?.keyframes.length ? (
              <div className={styles.keyframeGrid}>
                {result.keyframes.map((keyframe) => {
                  const imageHref = toLocalAsset(keyframe.frame.imagePath);
                  return (
                    <article key={keyframe.frame.frameId} className={styles.keyframeCard}>
                      {imageHref ? <img className={styles.keyframeImage} src={imageHref} alt={keyframe.description || keyframe.frame.label} /> : <div className={styles.keyframeImage} />}
                      <div className={styles.keyframeBody}>
                        <div className={styles.keyframeTop}>
                          <div className={styles.keyframeTime}>{formatRulerLabel(keyframe.frame.timeMs)}</div>
                          <button type="button" className={styles.ghostButton} onClick={() => void handleSeek(keyframe.frame.timeMs)}>
                            <LocateFixed size={14} />
                            定位
                          </button>
                        </div>
                        <div className={styles.keyframeDescription}>{keyframe.description || keyframe.frame.label}</div>
                        <div className={styles.keyframeActions}>
                          {imageHref && (
                            <a className={styles.downloadButton} href={imageHref} download={downloadName(keyframe.frame.imagePath, `${keyframe.frame.frameId}.jpg`)}>
                              <Download size={14} />
                              下載影格
                            </a>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className={styles.emptyCard}>
                AI 分析完成後，這裡會顯示 8 到 10 張帶標記關鍵幀與說明。
              </div>
            )}
          </section>

          <section className={styles.summaryCard}>
            <div className={styles.summaryHeader}>
              <div className={styles.summaryTitle}>
                <Clock3 size={16} />
                追蹤同步
              </div>
            </div>
            <div className={styles.summaryText}>
              目前 playhead：{formatRulerLabel(snapshot?.playheadMs ?? 0)}。AI 執行完成後，preview 與 Plate 面板會同步套用相同的 target track、samples、candidates 與車牌結果。
            </div>
          </section>
        </main>
      </div>
    </div>
  );
};