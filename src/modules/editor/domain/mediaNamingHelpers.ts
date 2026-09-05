import { formatTransportTime, type EditorFileState } from './model';

export function replaceExtension(fileName: string, extension: string) {
  const dotIndex = fileName.lastIndexOf('.');
  if (dotIndex === -1) {
    return `${fileName}.${extension}`;
  }

  return `${fileName.slice(0, dotIndex)}.${extension}`;
}

export function frameExportExtension(fileState?: EditorFileState) {
  return fileState?.renderProfile?.compressionMode === 'compact' ? 'jpg' : 'png';
}

export function defaultFrameFileName(fileState: EditorFileState, playheadMs: number) {
  const extension = frameExportExtension(fileState);
  const baseName = replaceExtension(fileState.asset.name, extension);
  const timeLabel = formatTransportTime(playheadMs).replace(/[:.]/g, '-');
  return replaceExtension(baseName, `${timeLabel}.${extension}`);
}

export function defaultLprEvidenceFileName(fileState: EditorFileState, playheadMs: number, candidateText: string | null) {
  const baseName = replaceExtension(fileState.asset.name, 'json');
  const timeLabel = formatTransportTime(playheadMs).replace(/[:.]/g, '-');
  const candidateLabel = candidateText ? `_${candidateText}` : '';
  return replaceExtension(baseName, `${timeLabel}${candidateLabel}.json`);
}
