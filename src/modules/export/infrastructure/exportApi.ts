import { emitTo } from '@tauri-apps/api/event';
import { commands } from '../../../types/bindings';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
import type { ExportSnapshot, TimelineExportRequest } from '../application/exportTypes';
import { createLogger } from '../../../utils/logger';
import {
  createRevisionedWindowSnapshot,
  focusExistingWindow,
  waitForWindowCreation,
  type RevisionedWindowSnapshot,
} from '../../../shared/windowing';
import {
  EXPORT_SESSION_REQUEST_EVENT,
  EXPORT_SESSION_UPDATED_EVENT,
  EXPORT_WINDOW_LABEL,
  EXPORT_WINDOW_URL,
  MAIN_WINDOW_LABEL,
} from '../application/exportWindow';

const log = createLogger('ExportWindowApi');

export async function processTimelineExport(request: TimelineExportRequest): Promise<void> {
  const res = await commands.processTimelineExport(request as any);
  if (res.status === 'ok') return;
  throw new Error(res.error);
}

export function syncExportWindowSession(snapshot: ExportSnapshot, revision = 0) {
  const payload: RevisionedWindowSnapshot<ExportSnapshot> = createRevisionedWindowSnapshot(snapshot, revision);
  return emitTo(EXPORT_WINDOW_LABEL, EXPORT_SESSION_UPDATED_EVENT, payload);
}

export function requestExportWindowSession() {
  return emitTo(MAIN_WINDOW_LABEL, EXPORT_SESSION_REQUEST_EVENT);
}

export async function openExportWindow(snapshot: ExportSnapshot, revision = 0) {
  log.info('Opening export window.', {
    workspaceName: snapshot.workspaceName,
    clipCount: snapshot.clips.length,
    trackCount: snapshot.tracks.length,
  });

  await syncExportWindowSession(snapshot, revision);

  const existingWindow = await focusExistingWindow(EXPORT_WINDOW_LABEL);
  if (existingWindow) {
    return existingWindow;
  }

  const exportWindow = new WebviewWindow(EXPORT_WINDOW_LABEL, {
    url: EXPORT_WINDOW_URL,
    title: 'Export Settings',
    width: 800,
    height: 720,
    minWidth: 700,
    minHeight: 680,
    center: true,
    resizable: true,
    focus: true,
    decorations: false,
    transparent: true,
  });

  return waitForWindowCreation(exportWindow);
}