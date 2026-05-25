import React from 'react';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { save } from '@tauri-apps/plugin-dialog';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2,
  FileOutput,
  FolderOpen,
  LoaderCircle,
  Music4,
  RefreshCcw,
  Video,
  X,
  Settings2,
  AlertTriangle,
} from 'lucide-react';
import { createLogger, getErrorMessage, serializeError } from '../../../utils/logger';
import { getPendingExportSession, processTimelineExport } from '../infrastructure/exportApi';
import type {
  AudioBitrateKbps,
  ExportSnapshot,
  ExportFormat,
  ExportProgressPayload,
  OutputCompressionMode,
  VideoQuality,
} from '../application/exportTypes';
import { formatTransportTime } from '../../editor/domain/model';
import styles from './ExportWindow.module.css';
import { Select } from '../../../components/Select/Select';

type ExportStatus = 'loading' | 'idle' | 'running' | 'done' | 'error';
const log = createLogger('ExportWindow');

const FORMAT_OPTIONS: Array<{
  value: ExportFormat;
  label: string;
}> = [
  { value: 'mp4', label: 'MP4' },
  { value: 'mkv', label: 'MKV' },
];

const VIDEO_QUALITY_OPTIONS: VideoQuality[] = ['source', '2160p', '1440p', '1080p', '720p', '480p'];
const AUDIO_BITRATE_OPTIONS: AudioBitrateKbps[] = [320, 256, 192, 128, 96];
const COMPRESSION_MODE_OPTIONS: OutputCompressionMode[] = ['standard', 'compact'];
const VIDEO_QUALITY_HEIGHTS: Record<Exclude<VideoQuality, 'source'>, number> = {
  '2160p': 2160,
  '1440p': 1440,
  '1080p': 1080,
  '720p': 720,
  '480p': 480,
};

const DEFAULT_PROGRESS: ExportProgressPayload = {
  progress: 0,
  stage: 'idle',
  detail: 'Ready to export.',
  done: false,
  failed: false,
};

function replaceOutputExtension(path: string, format: ExportFormat) {
  if (!path) {
    return path;
  }

  const lastSlashIndex = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  const lastDotIndex = path.lastIndexOf('.');
  if (lastDotIndex <= lastSlashIndex) {
    return `${path}.${format}`;
  }

  return `${path.slice(0, lastDotIndex)}.${format}`;
}

function defaultFormatForSession(snapshot: ExportSnapshot | null): ExportFormat {
  return snapshot?.renderProfile.format ?? 'mp4';
}

function suggestedFilename(snapshot: ExportSnapshot | null, format: ExportFormat) {
  return `${snapshot?.suggestedName?.trim() || 'timeline-export'}.${format}`;
}

function makeEvenDimension(value: number) {
  const normalized = Math.max(2, Math.round(value));
  return normalized % 2 === 0 ? normalized : normalized - 1;
}

function scaledDimensionsForQuality(width: number, height: number, quality: VideoQuality) {
  const sourceWidth = makeEvenDimension(width);
  const sourceHeight = makeEvenDimension(height);
  if (quality === 'source') {
    return { width: sourceWidth, height: sourceHeight };
  }

  const targetHeight = VIDEO_QUALITY_HEIGHTS[quality];
  if (sourceHeight <= targetHeight) {
    return { width: sourceWidth, height: sourceHeight };
  }

  const scale = targetHeight / sourceHeight;
  return {
    width: makeEvenDimension(sourceWidth * scale),
    height: makeEvenDimension(targetHeight),
  };
}

function buildVideoQualityOptions(snapshot: ExportSnapshot | null): Array<{ value: VideoQuality; label: string }> {
  if (!snapshot?.dominantWidth || !snapshot?.dominantHeight) {
    return [{ value: 'source', label: 'Original' }];
  }

  const sourceDimensions = scaledDimensionsForQuality(snapshot.dominantWidth, snapshot.dominantHeight, 'source');
  const options: Array<{ value: VideoQuality; label: string }> = [{
    value: 'source',
    label: `${sourceDimensions.height}p (${sourceDimensions.width}x${sourceDimensions.height})`,
  }];

  for (const quality of VIDEO_QUALITY_OPTIONS) {
    if (quality === 'source') {
      continue;
    }

    const dimensions = scaledDimensionsForQuality(snapshot.dominantWidth, snapshot.dominantHeight, quality);
    if (dimensions.width === sourceDimensions.width && dimensions.height === sourceDimensions.height) {
      continue;
    }

    options.push({
      value: quality,
      label: `${quality} (${dimensions.width}x${dimensions.height})`,
    });
  }

  return options;
}

function normalizeVideoQuality(snapshot: ExportSnapshot | null, requestedQuality: VideoQuality) {
  const availableQualities = new Set(buildVideoQualityOptions(snapshot).map((option) => option.value));
  return availableQualities.has(requestedQuality) ? requestedQuality : 'source';
}

export const ExportWindow: React.FC = () => {
  const [snapshot, setSnapshot] = React.useState<ExportSnapshot | null>(null);
  const [format, setFormat] = React.useState<ExportFormat>('mp4');
  const [videoQuality, setVideoQuality] = React.useState<VideoQuality>('source');
  const [audioBitrateKbps, setAudioBitrateKbps] = React.useState<AudioBitrateKbps>(320);
  const [compressionMode, setCompressionMode] = React.useState<OutputCompressionMode>('standard');
  const [outputPath, setOutputPath] = React.useState('');
  const [progress, setProgress] = React.useState<ExportProgressPayload>(DEFAULT_PROGRESS);
  const [status, setStatus] = React.useState<ExportStatus>('loading');
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  const usesAudioBitrate = true;
  const videoQualityOptions = React.useMemo(() => buildVideoQualityOptions(snapshot), [snapshot]);

  const applySnapshot = React.useCallback((nextSnapshot: ExportSnapshot | null) => {
    if (!nextSnapshot) {
      setSnapshot(null);
      setStatus('error');
      setErrorMessage('No timeline is queued for export yet.');
      return;
    }

    setSnapshot(nextSnapshot);
    setFormat(defaultFormatForSession(nextSnapshot));
  setVideoQuality(normalizeVideoQuality(nextSnapshot, nextSnapshot.renderProfile.videoQuality ?? 'source'));
    setAudioBitrateKbps(nextSnapshot.renderProfile.audioBitrateKbps ?? 320);
    setCompressionMode(nextSnapshot.renderProfile.compressionMode);
    setOutputPath('');
    setProgress(DEFAULT_PROGRESS);
    setStatus('idle');
    setErrorMessage(null);
  }, []);

  const loadPendingSession = React.useCallback(async () => {
    const nextSnapshot = await getPendingExportSession();
    log.info('Loaded pending export session.', nextSnapshot ? {
      workspaceName: nextSnapshot.workspaceName,
      clipCount: nextSnapshot.clips.length,
    } : 'empty');
    return nextSnapshot;
  }, []);

  const refreshSession = React.useCallback(async () => {
    setStatus('loading');
    setErrorMessage(null);

    try {
      applySnapshot(await loadPendingSession());
    } catch (error) {
      log.error('Failed to load export session.', serializeError(error));
      setStatus('error');
      setErrorMessage(getErrorMessage(error, 'Failed to load export session.'));
    }
  }, [applySnapshot, loadPendingSession]);

  const handleFormatChange = React.useCallback((nextFormat: ExportFormat) => {
    setFormat(nextFormat);
    setOutputPath((currentPath) => (currentPath ? replaceOutputExtension(currentPath, nextFormat) : currentPath));
  }, []);

  React.useEffect(() => {
    let disposed = false;
    let removeSessionListener: (() => void) | undefined;
    let removeProgressListener: (() => void) | undefined;

    const loadInitialSession = async () => {
      try {
        const nextSnapshot = await loadPendingSession();
        if (disposed) {
          return;
        }

        applySnapshot(nextSnapshot);
      } catch (error) {
        if (disposed) {
          return;
        }

        log.error('Failed to load export session.', serializeError(error));
        setStatus('error');
        setErrorMessage(getErrorMessage(error, 'Failed to load export session.'));
      }
    };

    void loadInitialSession();

    void listen<ExportSnapshot>('editor/export-session-updated', (event) => {
      if (disposed) return;
      applySnapshot(event.payload);
    }).then((unlisten) => {
      removeSessionListener = unlisten;
    });

    void listen<ExportProgressPayload>('editor/export-progress', (event) => {
      if (disposed) return;
      const nextProgress = {
        ...event.payload,
        progress: Math.max(0, Math.min(1, event.payload.progress)),
      };
      setProgress(nextProgress);

      if (nextProgress.failed) {
        setStatus('error');
        setErrorMessage(nextProgress.detail);
        return;
      }
      if (nextProgress.done) {
        setStatus('done');
        setErrorMessage(null);
        return;
      }
      setStatus('running');
    }).then((unlisten) => {
      removeProgressListener = unlisten;
    });

    return () => {
      disposed = true;
      removeSessionListener?.();
      removeProgressListener?.();
    };
  }, [applySnapshot, loadPendingSession]);

  const pickOutputPath = React.useCallback(async () => {
    const selectedPath = await save({
      title: 'Export timeline',
      defaultPath: outputPath || suggestedFilename(snapshot, format),
      filters: [{ name: format.toUpperCase(), extensions: [format] }],
    });

    if (!selectedPath) return null;

    const normalizedPath = selectedPath.toLowerCase().endsWith(`.${format}`)
      ? selectedPath
      : `${selectedPath}.${format}`;
    setOutputPath(normalizedPath);
    return normalizedPath;
  }, [format, outputPath, snapshot]);

  const handleExport = React.useCallback(async () => {
    if (!snapshot || status === 'running') return;

    setErrorMessage(null);
    setStatus('running');
    setProgress({
      progress: 0.01,
      stage: 'prepare',
      detail: 'Preparing export command...',
      done: false,
      failed: false,
    });

    try {
      let finalPath = outputPath || (await pickOutputPath());
      if (!finalPath) {
        setStatus('idle');
        setProgress(DEFAULT_PROGRESS);
        return;
      }

      // Final safety check for extension synchronization
      if (!finalPath.toLowerCase().endsWith(`.${format}`)) {
        const lastDot = finalPath.lastIndexOf('.');
        if (lastDot !== -1) {
          finalPath = `${finalPath.slice(0, lastDot)}.${format}`;
        } else {
          finalPath = `${finalPath}.${format}`;
        }
        setOutputPath(finalPath);
      }

      await processTimelineExport({
        outputPath: finalPath,
        profile: {
          format,
          fps: snapshot.renderProfile.fps,
          videoQuality,
          audioBitrateKbps,
          compressionMode,
        },
        snapshot,
      });
    } catch (error) {
      const message = getErrorMessage(error, 'Export failed.');
      setStatus('error');
      setErrorMessage(message);
      setProgress({
        progress: 0,
        stage: 'error',
        detail: message,
        done: false,
        failed: true,
      });
    }
  }, [audioBitrateKbps, compressionMode, format, outputPath, pickOutputPath, snapshot, status, videoQuality]);

  const handleClose = async () => {
    await getCurrentWindow().close();
  };

  return (
    <div className={styles.windowContainer}>
      <header className={styles.titlebar} data-tauri-drag-region>
        <div className={styles.titlebarLeft} data-tauri-drag-region>
          <Settings2 size={16} />
          <span>Export Options</span>
        </div>
        <button className={styles.closeButton} onClick={handleClose}>
          <X size={16} />
        </button>
      </header>

      <main className={styles.mainContent}>
        <AnimatePresence mode="wait">
          {!snapshot ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className={styles.emptyState}
            >
              <div className={styles.iconCircle}>
                <AlertTriangle size={24} />
              </div>
              <p>{errorMessage ?? 'No pending timeline export.'}</p>
              <button className={styles.outlineBtn} onClick={() => void refreshSession()}>
                <RefreshCcw size={14} /> Refresh
              </button>
            </motion.div>
          ) : (
            <motion.div
              key="content"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className={styles.contentLayout}
            >
              {/* Top Section: Overview */}
              <div className={styles.sessionOverview}>
                <div className={styles.workspaceName}>{snapshot.workspaceName}</div>
                <div className={styles.metaRow}>
                  <div className={styles.metaBadge}>{snapshot.fileName}</div>
                  <div className={styles.metaBadge}>
                    <Video size={14} />
                    {snapshot.dominantWidth && snapshot.dominantHeight
                      ? `${snapshot.dominantWidth}x${snapshot.dominantHeight}`
                      : 'Video'}
                  </div>
                  <div className={styles.metaBadge}>
                    <Music4 size={14} />
                    {formatTransportTime(snapshot.timelineDurationMs)}
                  </div>
                  <div className={styles.metaBadge}>
                    {snapshot.clips.length} Clips
                  </div>
                </div>
              </div>

              {/* Form Settings */}
              <div className={styles.settingsPanel}>
                <div className={styles.settingGroup}>
                  <label>Format</label>
                  <div className={styles.formatSelector}>
                    {FORMAT_OPTIONS.map((opt) => {
                      const isActive = format === opt.value;
                      return (
                        <button
                          key={opt.value}
                          onClick={() => handleFormatChange(opt.value)}
                          className={`${styles.formatPill} ${isActive ? styles.active : ''}`}
                        >
                          {isActive && (
                            <motion.div
                              layoutId="formatPillBg"
                              className={styles.pillBg}
                              initial={false}
                              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                            />
                          )}
                          <span className={styles.pillText}>{opt.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className={styles.settingGroup}>
                  <label>Resolution</label>
                  <div className={styles.selectWrapper}>
                    <Select
                      value={videoQuality}
                      onChange={(value) => setVideoQuality(normalizeVideoQuality(snapshot, value as VideoQuality))}
                      options={videoQualityOptions.map((option) => ({
                        value: option.value,
                        label: option.label,
                      }))}
                    />
                  </div>
                </div>

                <div className={styles.settingGroup}>
                  <label>Size Mode</label>
                  <div className={styles.formatSelector}>
                    {COMPRESSION_MODE_OPTIONS.map((option) => {
                      const isActive = compressionMode === option;
                      return (
                        <button
                          key={option}
                          onClick={() => setCompressionMode(option)}
                          className={`${styles.formatPill} ${isActive ? styles.active : ''}`}
                        >
                          {isActive && (
                            <motion.div
                              layoutId="compressionPillBg"
                              className={styles.pillBg}
                              initial={false}
                              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                            />
                          )}
                          <span className={styles.pillText}>{option === 'compact' ? 'Compact' : 'Standard'}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className={styles.settingGroup}>
                  <label>Audio Bitrate</label>
                  <div className={styles.selectWrapper}>
                    <Select
                      value={audioBitrateKbps.toString()}
                      onChange={(val) => setAudioBitrateKbps(Number(val) as AudioBitrateKbps)}
                      disabled={!usesAudioBitrate}
                      options={AUDIO_BITRATE_OPTIONS.map((opt) => ({
                        value: opt.toString(),
                        label: `${opt} kbps`,
                      }))}
                    />
                  </div>
                </div>

                <div className={styles.settingGroup}>
                  <label>Save to</label>
                  <div className={styles.pathInputGroup}>
                    <input
                      type="text"
                      placeholder={suggestedFilename(snapshot, format)}
                      value={outputPath}
                      onChange={(e) => setOutputPath(e.target.value)}
                      className={styles.pathInput}
                    />
                    <button className={styles.folderBtn} onClick={() => void pickOutputPath()}>
                      <FolderOpen size={16} />
                    </button>
                  </div>
                </div>
              </div>

              {/* Progress & Action */}
              <div className={styles.actionPanel}>
                <AnimatePresence mode="wait">
                  {status === 'running' ? (
                    <motion.div
                      key="running"
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      className={styles.progressContainer}
                    >
                      <div className={styles.progressHeader}>
                        <span className={styles.progressDetail}>{progress.detail}</span>
                        <span className={styles.progressPercent}>{Math.round(progress.progress * 100)}%</span>
                      </div>
                      <div className={styles.progressBarBg}>
                        <motion.div
                          className={styles.progressBarFill}
                          initial={{ width: 0 }}
                          animate={{ width: `${progress.progress * 100}%` }}
                          transition={{ ease: 'linear', duration: 0.2 }}
                        />
                      </div>
                    </motion.div>
                  ) : status === 'done' ? (
                    <motion.div
                      key="done"
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className={styles.successMessage}
                    >
                      <CheckCircle2 size={18} />
                      <span>Export completed successfully</span>
                    </motion.div>
                  ) : status === 'error' && errorMessage ? (
                    <motion.div
                      key="error"
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className={styles.errorMessage}
                    >
                      <AlertTriangle size={16} />
                      <span>{errorMessage}</span>
                    </motion.div>
                  ) : null}
                </AnimatePresence>

                <div className={styles.actionRow}>
                  <button className={styles.secondaryBtn} onClick={handleClose}>
                    Cancel
                  </button>
                  <motion.button
                    className={styles.primaryBtn}
                    onClick={() => void handleExport()}
                    disabled={status === 'running'}
                    whileHover={{ scale: status === 'running' ? 1 : 1.02 }}
                    whileTap={{ scale: status === 'running' ? 1 : 0.98 }}
                  >
                    {status === 'running' ? (
                      <LoaderCircle className={styles.spin} size={18} />
                    ) : (
                      <FileOutput size={18} />
                    )}
                    {status === 'running' ? 'Rendering...' : 'Export Media'}
                  </motion.button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
};