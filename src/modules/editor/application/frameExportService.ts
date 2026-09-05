import { save } from '@tauri-apps/plugin-dialog';
import type { EditorFileState } from '../domain/model';
import { findClipAtPlayhead } from '../domain/model';
import { defaultFrameFileName, frameExportExtension } from '../domain/mediaNamingHelpers';
import { exportFrameImage } from '../infrastructure/mediaApi';
import { createLogger, getErrorSummary, serializeError } from '../../../utils/logger';

const log = createLogger('frameExportService');

export interface ExportCurrentFrameOptions {
  activeFile: EditorFileState | null | undefined;
  playheadMs: number;
  previewVideoElement: HTMLVideoElement | null;
  setFeedback: (msg: string | null) => void;
  stopPlayback?: () => void;
}

export async function exportCurrentFrame({
  activeFile,
  playheadMs,
  previewVideoElement,
  setFeedback,
  stopPlayback,
}: ExportCurrentFrameOptions): Promise<void> {
  if (!activeFile || activeFile.asset.status !== 'ready') {
    setFeedback('Select a ready video file before exporting a frame.');
    return;
  }

  stopPlayback?.();

  const clip = findClipAtPlayhead(activeFile.clips, playheadMs);
  if (!clip) {
    setFeedback('Move the playhead onto a visible clip before exporting a frame.');
    return;
  }

  const extension = frameExportExtension(activeFile);
  const filterName = extension === 'jpg' ? 'JPEG Image' : 'PNG Image';
  const selectedPath = await save({
    title: 'Export current frame',
    defaultPath: defaultFrameFileName(activeFile, playheadMs),
    filters: [{ name: filterName, extensions: [extension] }],
  });

  if (!selectedPath) {
    return;
  }

  const outputPath = selectedPath.toLowerCase().endsWith(`.${extension}`) ? selectedPath : `${selectedPath}.${extension}`;
  const exportTimeMs = previewVideoElement && Number.isFinite(previewVideoElement.currentTime)
    ? previewVideoElement.currentTime * 1000
    : clip.inPointMs + (playheadMs - clip.startMs);

  try {
    await exportFrameImage({
      outputPath,
      sourcePath: activeFile.asset.path,
      timeMs: exportTimeMs,
      markerRect: activeFile.markerRect,
      compressionMode: activeFile.renderProfile.compressionMode,
    });
    setFeedback(`Frame exported to ${outputPath}`);
  } catch (error) {
    log.error('Failed to export the current frame.', serializeError(error));
    setFeedback(getErrorSummary(error, 'Failed to export the current frame.'));
  }
}
