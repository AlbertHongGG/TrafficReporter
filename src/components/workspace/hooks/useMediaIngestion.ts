import { useCallback, useEffect, useState } from 'react';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import { open } from '@tauri-apps/plugin-dialog';
import type { EditorAsset } from '../../../modules/editor/domain/model';
import type { EditorAction } from '../../../modules/editor/application/editorReducer';
import { buildEditorAsset, isSupportedMediaPath } from '../../../modules/editor/infrastructure/mediaApi';
import { createLogger, getErrorSummary, serializeError } from '../../../utils/logger';

const log = createLogger('useMediaIngestion');

export interface UseMediaIngestionOptions {
  dispatch: React.Dispatch<EditorAction>;
  stopPlayback?: () => void;
}

export function useMediaIngestion({ dispatch, stopPlayback }: UseMediaIngestionOptions) {
  const [isExternalDropActive, setIsExternalDropActive] = useState(false);
  const [importFeedback, setImportFeedback] = useState<string | null>(null);

  const handleSelectFile = useCallback((fileId: string) => {
    stopPlayback?.();
    dispatch({ type: 'set-active-file', fileId });
  }, [dispatch, stopPlayback]);

  const handleRemoveFile = useCallback((fileId: string) => {
    stopPlayback?.();
    dispatch({ type: 'remove-file', fileId });
  }, [dispatch, stopPlayback]);

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
        dispatch({ type: 'add-files', assets });
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
  }, [dispatch]);

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
      dispatch({ type: 'relink-file', fileId, asset });
      setImportFeedback(null);
    } catch (error) {
      log.error('Failed to relink media file.', serializeError(error));
      setImportFeedback(getErrorSummary(error, 'Failed to relink video.'));
    }
  }, [dispatch]);

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
