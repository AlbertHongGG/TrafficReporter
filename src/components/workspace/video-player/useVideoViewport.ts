import { useCallback, useEffect, useState } from 'react';

export interface PreviewViewport {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function fitContainedViewport(containerWidth: number, containerHeight: number, sourceWidth: number, sourceHeight: number): PreviewViewport {
  if (containerWidth <= 0 || containerHeight <= 0 || sourceWidth <= 0 || sourceHeight <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }

  const scale = Math.min(containerWidth / sourceWidth, containerHeight / sourceHeight);
  const width = sourceWidth * scale;
  const height = sourceHeight * scale;

  return {
    left: (containerWidth - width) / 2,
    top: (containerHeight - height) / 2,
    width,
    height,
  };
}

export function useVideoViewport(
  previewContainerRef: React.RefObject<HTMLDivElement | null>,
  previewVideoRef: React.RefObject<HTMLVideoElement | null>,
  activeFileAssetWidth: number | undefined,
  activeFileAssetHeight: number | undefined,
  activeFileId: string | undefined,
  previewAssetId: string | undefined
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
