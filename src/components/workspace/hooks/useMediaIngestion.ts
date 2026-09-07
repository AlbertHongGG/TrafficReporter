import { useCallback, useEffect, useState } from 'react';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import { open } from '@tauri-apps/plugin-dialog';
import type { EditorAsset } from '../../../modules/editor/domain/model';
import { useEditorStore } from '../../../modules/editor/application/store/store';
import { editorWorkspaceTransport } from '../../../modules/editor/application/editorSessionSync';
import { buildEditorAsset, isSupportedMediaPath } from '../../../modules/editor/infrastructure/mediaApi';
import { createLogger, getErrorSummary, serializeError } from '../../../utils/logger';

const log = createLogger('useMediaIngestion');

export interface UseMediaIngestionOptions {
  stopPlayback?: () => void;
}

export function useMediaIngestion({ stopPlayback }: UseMediaIngestionOptions) {
  const [isExternalDropActive, setIsExternalDropActive] = useState(false);
  const [importFeedback, setImportFeedback] = useState<string | null>(null);

  const handleSelectFile = useCallback((fileId: string) => {
    stopPlayback?.();
    editorWorkspaceTransport.setActiveFile(fileId);
  }, [stopPlayback]);

  const handleRemoveFile = useCallback((fileId: string) => {
    stopPlayback?.();
    editorWorkspaceTransport.removeFile(fileId);
  }, [stopPlayback]);

  const importMediaPaths = useCallback(async (paths: string[]) => {
    const filtered = [...new Set(paths)].filter(isSupportedMediaPath);
    if (filtered.length === 0) {
      setImportFeedback('No supported video files were selected.');
      return;
    }

    setImportFeedback(null);

    try {
      const results = await Promise.allSettled(filtered.map((path) => buildEditorAsset(path)));
      const assets = results
        .filter((result): result is PromiseFulfilledResult<EditorAsset> => result.status === 'fulfilled')
        .map((result) => result.value);
      const failures = results.filter((result) => result.status === 'rejected');

      if (assets.length > 0) {
        editorWorkspaceTransport.addFiles(assets);
      }

      if (failures.length > 0) {
        log.warn('Some selected files failed to import.', {
          failureCount: failures.length,
          firstFailure: serializeError(failures[0].reason),
        });
        setImportFeedback(
          getErrorSummary(
            failures[0].reason,
            `${failures.length} file(s) failed to import.`,
          ),
        );
      }
    } catch (error) {
      log.error('Media import failed.', serializeError(error));
      setImportFeedback(getErrorSummary(error, 'Failed to import media.'));
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;

    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (event.payload.type === 'enter' || event.payload.type === 'over') {
          setIsExternalDropActive(true);
          return;
        }

        if (event.payload.type === 'leave') {
          setIsExternalDropActive(false);
          return;
        }

        setIsExternalDropActive(false);
        void importMediaPaths(event.payload.paths);
      })
      .then((cleanup) => {
        if (disposed) {
          cleanup();
          return;
        }

        unlisten = cleanup;
      })
      .catch(() => {
        /* dialog import remains available if drag-drop registration fails */
      });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [importMediaPaths]);

  const handleImportClick = useCallback(async () => {
    const selection = await open({
      multiple: true,
      title: 'Import video files',
      filters: [
        {
          name: 'Video',
          extensions: ['mp4', 'mkv', 'mov', 'webm', 'avi', 'm4v'],
        },
      ],
    });

    if (!selection) {
      return;
    }

    await importMediaPaths(Array.isArray(selection) ? selection : [selection]);
  }, [importMediaPaths]);

  const handleRelinkFile = useCallback(async (fileId: string) => {
    const selection = await open({
      multiple: false,
      title: 'Relink video file',
      filters: [
        {
          name: 'Video',
          extensions: ['mp4', 'mkv', 'mov', 'webm', 'avi', 'm4v'],
        },
      ],
    });

    if (!selection || Array.isArray(selection)) {
      return;
    }

    try {
      const asset = await buildEditorAsset(selection);
      useEditorStore.getState().relinkFile(fileId, asset);
      setImportFeedback(null);
    } catch (error) {
      log.error('Failed to relink media file.', serializeError(error));
      setImportFeedback(getErrorSummary(error, 'Failed to relink video.'));
    }
  }, []);

  return {
    isExternalDropActive,
    importFeedback,
    setImportFeedback,
    importMediaPaths,
    handleImportClick,
    handleRelinkFile,
    handleSelectFile,
    handleRemoveFile,
  };
}
