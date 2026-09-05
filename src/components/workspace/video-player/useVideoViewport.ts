import { useCallback, useEffect, useState } from 'react';
import {
  fitContainedViewport,
  type PreviewViewport,
} from '../../../modules/editor/domain/viewportHelpers';

export { fitContainedViewport, type PreviewViewport };

export function useVideoViewport(
  previewContainerRef: React.RefObject<HTMLDivElement | null>,
  previewVideoRef: React.RefObject<HTMLVideoElement | null>,
  activeFileAssetWidth: number | null | undefined,
  activeFileAssetHeight: number | null | undefined,
  activeFileId: string | null | undefined,
  previewAssetId: string | null | undefined
) {
  const [previewViewport, setPreviewViewport] = useState<PreviewViewport>({ left: 0, top: 0, width: 0, height: 0 });

  const refreshPreviewViewport = useCallback(() => {
    const container = previewContainerRef.current;
    if (!container) {
      return;
    }

    const sourceWidth = previewVideoRef.current?.videoWidth || activeFileAssetWidth || 1920;
    const sourceHeight = previewVideoRef.current?.videoHeight || activeFileAssetHeight || 1080;
    setPreviewViewport(
      fitContainedViewport(
        container.clientWidth,
        container.clientHeight,
        sourceWidth,
        sourceHeight,
      ),
    );
  }, [activeFileAssetHeight, activeFileAssetWidth, previewContainerRef, previewVideoRef]);

  useEffect(() => {
    refreshPreviewViewport();
  }, [activeFileId, previewAssetId, refreshPreviewViewport]);

  useEffect(() => {
    const container = previewContainerRef.current;
    const video = previewVideoRef.current;
    if (!container) {
      return undefined;
    }

    const observer = new ResizeObserver(refreshPreviewViewport);
    observer.observe(container);
    video?.addEventListener('loadedmetadata', refreshPreviewViewport);

    return () => {
      observer.disconnect();
      video?.removeEventListener('loadedmetadata', refreshPreviewViewport);
    };
  }, [previewContainerRef, previewVideoRef, refreshPreviewViewport]);

  return { previewViewport };
}
