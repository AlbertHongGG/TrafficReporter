import type { EditorWorkspaceState } from '../../editor/domain/model';
import { getActiveFile, getTimelineDuration } from '../../editor/domain/model';
import type { ExportSnapshot } from './exportTypes';

const INVALID_FILE_NAME_CHARACTERS = new Set(['<', '>', ':', '"', '/', '\\', '|', '?', '*']);

function sanitizeSuggestedName(name: string) {
  const cleaned = name
    .trim()
    .split('')
    .map((character) => {
      const codePoint = character.charCodeAt(0);
      return codePoint <= 31 || INVALID_FILE_NAME_CHARACTERS.has(character) ? '-' : character;
    })
    .join('')
    .replace(/\s+/g, ' ')
    .trim();

  return cleaned || 'timeline-export';
}

export function preparePendingExportSession(state: EditorWorkspaceState): ExportSnapshot {
  const activeFile = getActiveFile(state);
  if (!activeFile) {
    throw new Error('Select a file before exporting.');
  }

  if (activeFile.clips.length === 0) {
    throw new Error('Add at least one clip to the timeline before exporting.');
  }

  if (activeFile.asset.status !== 'ready' || !activeFile.asset.path) {
    throw new Error(`Relink missing media before exporting: ${activeFile.asset.name}`);
  }

  const suggestedName = sanitizeSuggestedName(activeFile.asset.name.replace(/\.[^.]+$/, ''));

  return {
    fileId: activeFile.id,
    fileName: activeFile.asset.name,
    workspaceName: state.workspaceName,
    suggestedName,
    timelineDurationMs: Math.round(getTimelineDuration(activeFile.clips)),
    hasVideo: activeFile.asset.hasVideo,
    hasAudio: activeFile.asset.hasAudio,
    dominantWidth: activeFile.asset.width,
    dominantHeight: activeFile.asset.height,
    sources: [{
      id: activeFile.asset.id,
      name: activeFile.asset.name,
      path: activeFile.asset.path,
      hasVideo: activeFile.asset.hasVideo,
      hasAudio: activeFile.asset.hasAudio,
      width: activeFile.asset.width,
      height: activeFile.asset.height,
    }],
    tracks: [{
      id: activeFile.track.id,
      name: activeFile.track.name,
      order: activeFile.track.order,
    }],
    clips: activeFile.clips.map((clip) => ({
      id: clip.id,
      assetId: clip.assetId,
      trackId: clip.trackId,
      startMs: Math.round(clip.startMs),
      inPointMs: Math.round(clip.inPointMs),
      outPointMs: Math.round(clip.outPointMs),
      muted: clip.muted,
    })),
    renderProfile: { ...activeFile.renderProfile },
  };
}
