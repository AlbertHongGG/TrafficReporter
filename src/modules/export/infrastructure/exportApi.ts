import { commands } from '../../../types/bindings';
import type {
  ExportSnapshotPayload,
  RenderProfilePayload,
  TimelineExportRequest as TimelineExportRequestPayload,
} from '../../../types/bindings';
import { unwrapCommand } from '../../../infrastructure/ipc-unwrap';
import { parseTimelineExportResponse } from './exportSchemas';
import type { ExportSnapshot, RenderProfile, TimelineExportRequest } from '../application/exportTypes';
import { createLogger } from '../../../utils/logger';
import { desktopWindowManager } from '../../../platform/desktop';
import {
  EXPORT_SESSION_REQUEST_EVENT,
  EXPORT_SESSION_UPDATED_EVENT,
  EXPORT_WINDOW_LABEL,
} from '../application/exportWindow';

const log = createLogger('ExportWindowApi');

function toRenderProfilePayload(profile: RenderProfile): RenderProfilePayload {
  return {
    format: profile.format,
    fps: profile.fps,
    videoQuality: profile.videoQuality ?? null,
    audioBitrateKbps: profile.audioBitrateKbps ?? null,
    compressionMode: profile.compressionMode,
  };
}

function toExportSnapshotPayload(snapshot: ExportSnapshot): ExportSnapshotPayload {
  return {
    fileId: snapshot.fileId,
    fileName: snapshot.fileName,
    workspaceName: snapshot.workspaceName,
    suggestedName: snapshot.suggestedName,
    timelineDurationMs: snapshot.timelineDurationMs,
    hasVideo: snapshot.hasVideo,
    hasAudio: snapshot.hasAudio,
    dominantWidth: snapshot.dominantWidth ?? null,
    dominantHeight: snapshot.dominantHeight ?? null,
    sources: snapshot.sources.map((source) => ({
      ...source,
      width: source.width ?? null,
      height: source.height ?? null,
    })),
    tracks: snapshot.tracks,
    clips: snapshot.clips,
    renderProfile: toRenderProfilePayload(snapshot.renderProfile),
  };
}

function toTimelineExportRequestPayload(request: TimelineExportRequest): TimelineExportRequestPayload {
  return {
    outputPath: request.outputPath,
    profile: toRenderProfilePayload(request.profile),
    snapshot: toExportSnapshotPayload(request.snapshot),
  };
}

export async function processTimelineExport(request: TimelineExportRequest): Promise<void> {
  const raw = await unwrapCommand(
    commands.processTimelineExport(toTimelineExportRequestPayload(request)),
    'process_timeline_export',
  );
  parseTimelineExportResponse('process_timeline_export', raw);
}

export function syncExportWindowSession(snapshot: ExportSnapshot, revision = 0) {
  return desktopWindowManager.broadcast(EXPORT_WINDOW_LABEL, EXPORT_SESSION_UPDATED_EVENT, snapshot, revision);
}

export function requestExportWindowSession() {
  return desktopWindowManager.sendToMain(EXPORT_SESSION_REQUEST_EVENT, null);
}

export async function openExportWindow(snapshot: ExportSnapshot, revision = 0) {
  log.info('Opening export window.', {
    workspaceName: snapshot.workspaceName,
    clipCount: snapshot.clips.length,
    trackCount: snapshot.tracks.length,
  });

  await syncExportWindowSession(snapshot, revision);
  return desktopWindowManager.open(EXPORT_WINDOW_LABEL);
}