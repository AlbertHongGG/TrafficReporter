import { emitTo } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';
import type { ExportSnapshot, TimelineExportRequest } from '../application/exportTypes';
import { createLogger, getErrorMessage, serializeError } from '../../../utils/logger';
import { createRevisionedWindowSnapshot, type RevisionedWindowSnapshot } from '../../../vnext/windowing/revisionedSnapshot';
import {
  EXPORT_SESSION_REQUEST_EVENT,
  EXPORT_SESSION_UPDATED_EVENT,
  EXPORT_WINDOW_LABEL,
  EXPORT_WINDOW_URL,
  MAIN_WINDOW_LABEL,
} from '../application/exportWindow';

const log = createLogger('ExportWindowApi');

export function processTimelineExport(request: TimelineExportRequest) {
  return invoke<void>('process_timeline_export', { request });
}

export async function syncExportWindowSession(snapshot: ExportSnapshot, revision = 0) {
  const payload: RevisionedWindowSnapshot<ExportSnapshot> = createRevisionedWindowSnapshot(snapshot, revision);
  await emitTo(EXPORT_WINDOW_LABEL, EXPORT_SESSION_UPDATED_EVENT, payload).catch((error) => {
    log.debug('Skipped pushing export session to a closed export window.', serializeError(error));
  });
}

export function requestExportWindowSession() {
  return emitTo(MAIN_WINDOW_LABEL, EXPORT_SESSION_REQUEST_EVENT);
}

function waitForWindowCreation(exportWindow: WebviewWindow) {
  return new Promise<WebviewWindow>((resolve, reject) => {
    let settled = false;
    let createdCleanup: (() => void) | undefined;
    let errorCleanup: (() => void) | undefined;
    const timeoutId = window.setTimeout(() => {
      settleReject(new Error('Timed out while creating the export window.'));
    }, 4000);

    const cleanup = () => {
      window.clearTimeout(timeoutId);
      createdCleanup?.();
      errorCleanup?.();
    };

    const settleResolve = () => {
      if (settled) {
        return;
      }

      settled = true;
      cleanup();
      resolve(exportWindow);
    };

    const settleReject = (error: unknown) => {
      if (settled) {
        return;
      }

      settled = true;
      cleanup();
      reject(error instanceof Error ? error : new Error(getErrorMessage(error, 'Failed to create export window.')));
    };

    void exportWindow.once('tauri://created', () => {
      log.info('Export window created successfully.');
      settleResolve();
    }).then((unlisten) => {
      createdCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });

    void exportWindow.once<string>('tauri://error', (event) => {
      const error = new Error(getErrorMessage(event.payload, 'Failed to create export window.'));
      log.error('Export window creation failed.', {
        event: serializeError(event.payload),
      });
      settleReject(error);
    }).then((unlisten) => {
      errorCleanup = unlisten;
    }).catch((error) => {
      settleReject(error);
    });
  });
}

export async function openExportWindow(snapshot: ExportSnapshot, revision = 0) {
  log.info('Opening export window.', {
    workspaceName: snapshot.workspaceName,
    clipCount: snapshot.clips.length,
    trackCount: snapshot.tracks.length,
  });

  await syncExportWindowSession(snapshot, revision);

  const existingWindow = await WebviewWindow.getByLabel(EXPORT_WINDOW_LABEL);
  if (existingWindow) {
    await existingWindow.setFocus().catch((error) => {
      log.warn('Failed to focus existing export window.', serializeError(error));
    });
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