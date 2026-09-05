import { useCallback, useEffect, useState } from 'react';
import type { EditorFileState, VideoMarkerRect } from '../../../modules/editor/domain/model';
import { clamp, DEFAULT_MARKER_RECT } from '../../../modules/editor/domain/model';
import type { EditorAction } from '../../../modules/editor/application/editorReducer';
import type { PreviewViewport } from '../../../modules/editor/domain/viewportHelpers';

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
  dispatch: React.Dispatch<EditorAction>;
}

export function useMarkerInteraction({
  activeFile,
  previewViewport,
  dispatch,
}: UseMarkerInteractionOptions) {
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
        dispatch({
          type: 'set-marker-rect',
          markerRect: {
            ...originRect,
            x: clamp(originRect.x + deltaX, 0, 1 - originRect.width),
            y: clamp(originRect.y + deltaY, 0, 1 - originRect.height),
          },
        });
        return;
      }

      dispatch({
        type: 'set-marker-rect',
        markerRect: {
          ...originRect,
          width: clamp(originRect.width + deltaX, 0.05, 1 - originRect.x),
          height: clamp(originRect.height + deltaY, 0.05, 1 - originRect.y),
        },
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
  }, [dispatch, markerInteraction, previewViewport.height, previewViewport.width]);

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
    dispatch({
      type: 'set-marker-rect',
      markerRect: activeFile?.markerRect ?? DEFAULT_MARKER_RECT,
    });
  }, [activeFile, dispatch]);

  return {
    markerInteraction,
    markerStyle,
    handleMarkerPointerDown,
    handleMarkerResizePointerDown,
    handleCreateMarker,
  };
}
