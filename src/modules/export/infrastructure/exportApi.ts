import { commands } from '../../../domain/ipc/bindings';
import type {
  ExportSnapshotPayload,
  RenderProfilePayload,
  TimelineExportRequest as TimelineExportRequestPayload,
} from '../../../domain/ipc/bindings';
import { unwrapCommand } from '../../../infrastructure/ipc-unwrap';
import { parseTimelineExportResponse } from './exportSchemas';
import type { ExportSnapshot, RenderProfile, TimelineExportRequest } from '../application/exportTypes';
import { createLogger } from '../../../utils/logger';
import { desktopWindowManager } from '../../../platform/desktop';
import { exportContract } from '../../../platform/transport/contracts';
import {
  requestSession,
  sendSession,
  type TransportBackend,
} from '../../../platform/transport/runtime';
import { EXPORT_WINDOW_LABEL } from '../application/exportWindow';

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

/**
 * Phase 5-D 絞殺：export 單一寫入源維持 main window，本函式為唯一 session
 * 發送入口（經 transport runtime.sendSession 走 exportContract 通道；wire
 * 事件名字串不變）。舊 desktopWindowManager.broadcast 直寫已移除，無雙寫。
 */
export function syncExportWindowSession(
  snapshot: ExportSnapshot,
  revision = 0,
  backend?: TransportBackend,
) {
  return sendSession(exportContract, snapshot, revision, backend);
}

/** window → main 索取最新 session（經 runtime.requestSession；payload 恆為 null）。 */
export function requestExportWindowSession(backend?: TransportBackend) {
  return requestSession(exportContract.requestEvent, backend);
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