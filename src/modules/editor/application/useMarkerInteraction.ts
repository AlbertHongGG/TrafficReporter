import { useCallback, useEffect, useState } from 'react';
import type { EditorFileState, VideoMarkerRect } from '../domain/model';
import { clamp, DEFAULT_MARKER_RECT } from '../domain/model';
import { useEditorStore } from './store/store';
import type { PreviewViewport } from '../domain/viewportHelpers';

export interface MarkerInteraction {
  type: 'move' | 'resize';
  pointerId: number;
  startClientX: number;
  startClientY: number;
  originRect: VideoMarkerRect;
}

export interface UseMarkerInteractionOptions {
  activeFile: EditorFileState | null | undefined;
  previewViewport: PreviewViewport;
}

export function useMarkerInteraction({
  activeFile,
  previewViewport,
}: UseMarkerInteractionOptions) {
  const setMarkerRect = useEditorStore((s) => s.setMarkerRect);
  const [markerInteraction, setMarkerInteraction] = useState<MarkerInteraction | null>(null);

  useEffect(() => {
    if (!markerInteraction || previewViewport.width <= 0 || previewViewport.height <= 0) {
      return undefined;
    }

    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerId !== markerInteraction.pointerId) {
        return;
      }

      const deltaX = (event.clientX - markerInteraction.startClientX) / previewViewport.width;
      const deltaY = (event.clientY - markerInteraction.startClientY) / previewViewport.height;
      const originRect = markerInteraction.originRect;

      if (markerInteraction.type === 'move') {
        setMarkerRect({
          ...originRect,
          x: clamp(originRect.x + deltaX, 0, 1 - originRect.width),
          y: clamp(originRect.y + deltaY, 0, 1 - originRect.height),
        });
        return;
      }

      setMarkerRect({
        ...originRect,
        width: clamp(originRect.width + deltaX, 0.05, 1 - originRect.x),
        height: clamp(originRect.height + deltaY, 0.05, 1 - originRect.y),
      });
    };

    const handlePointerUp = (event: PointerEvent) => {
      if (event.pointerId !== markerInteraction.pointerId) {
        return;
      }

      setMarkerInteraction(null);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [markerInteraction, previewViewport.height, previewViewport.width, setMarkerRect]);

  const handleMarkerPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!activeFile?.markerRect) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    setMarkerInteraction({
      type: 'move',
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originRect: activeFile.markerRect,
    });
  }, [activeFile]);

  const handleMarkerResizePointerDown = useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
    if (!activeFile?.markerRect) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    setMarkerInteraction({
      type: 'resize',
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originRect: activeFile.markerRect,
    });
  }, [activeFile]);

  const markerStyle: React.CSSProperties | undefined = activeFile?.markerRect
    ? {
        left: `${previewViewport.left + activeFile.markerRect.x * previewViewport.width}px`,
        top: `${previewViewport.top + activeFile.markerRect.y * previewViewport.height}px`,
        width: `${activeFile.markerRect.width * previewViewport.width}px`,
        height: `${activeFile.markerRect.height * previewViewport.height}px`,
      }
    : undefined;

  const handleCreateMarker = useCallback(() => {
    setMarkerRect(activeFile?.markerRect ?? DEFAULT_MARKER_RECT);
  }, [activeFile, setMarkerRect]);

  return {
    markerInteraction,
    markerStyle,
    handleMarkerPointerDown,
    handleMarkerResizePointerDown,
    handleCreateMarker,
  };
}
