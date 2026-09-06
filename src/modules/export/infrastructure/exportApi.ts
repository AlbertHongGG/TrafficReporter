import { commands } from '../../../types/bindings';
import type { ExportSnapshot, TimelineExportRequest } from '../application/exportTypes';
import { createLogger } from '../../../utils/logger';
import { desktopWindowManager } from '../../../platform/desktop';
import {
  EXPORT_SESSION_REQUEST_EVENT,
  EXPORT_SESSION_UPDATED_EVENT,
  EXPORT_WINDOW_LABEL,
} from '../application/exportWindow';

const log = createLogger('ExportWindowApi');

export async function processTimelineExport(request: TimelineExportRequest): Promise<void> {
  const res = await commands.processTimelineExport(request as any);
  if (res.status === 'ok') return;
  throw new Error(res.error);
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