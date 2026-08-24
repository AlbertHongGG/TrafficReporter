import React from 'react';
import { Film, Square, X } from 'lucide-react';
import { useEditorContext } from '../workspace/EditorContext';
import { LprPreviewOverlayLayer } from './LprPreviewOverlayLayer';
import type { PlaybackPreviewState } from '../../modules/editor/application/usePlaybackController';
import type { LiveTransportStore } from '../../modules/editor/application/liveTransport';
import type { LprSessionState, LprTargetTrack } from '../../shared/contracts';
import type { PreviewViewport } from './useVideoViewport';
import styles from '../workspace/MainWorkspace.module.css';

interface VideoPlayerPanelProps {
  previewContainerRef: React.RefObject<HTMLDivElement | null>;
  previewVideoRef: React.RefObject<HTMLVideoElement | null>;
  previewState: PlaybackPreviewState;
  previewViewport: PreviewViewport;
  lprState: LprSessionState;
  lprAnalysisTrack: LprTargetTrack | null;
  liveTransportStore: LiveTransportStore;
  handleSelectTargetTrack: (targetTrackId: string, preferredTimeMs?: number | null) => void;
  markerStyle: React.CSSProperties | undefined;
  handleMarkerPointerDown: React.PointerEventHandler<HTMLDivElement>;
  handleMarkerResizePointerDown: React.PointerEventHandler<HTMLButtonElement>;
  handleCreateMarker: () => void;
}

export const VideoPlayerPanel: React.FC<VideoPlayerPanelProps> = ({
  previewContainerRef,
  previewVideoRef,
  previewState,
  previewViewport,
  lprState,
  lprAnalysisTrack,
  liveTransportStore,
  handleSelectTargetTrack,
  markerStyle,
  handleMarkerPointerDown,
  handleMarkerResizePointerDown,
  handleCreateMarker,
}) => {
  const { activeFile, dispatch } = useEditorContext();

  return (
    <section className={styles.previewPanel}>
      <div ref={previewContainerRef} className={styles.previewContainer}>
        <video
          ref={previewVideoRef as React.RefObject<HTMLVideoElement>}
          className={`${styles.previewVideo} ${!previewState.hasActiveVideo ? styles.previewVideoHidden : ''}`}
          playsInline
          preload="auto"
        />

        {!previewState.hasActiveVideo && (
          <div className={styles.previewPlaceholder}>
            <Film size={32} />
          </div>
        )}

        {activeFile && previewViewport.width > 0 && (
          <div className={styles.previewMarkerLayer}>
            <LprPreviewOverlayLayer
              previewViewport={previewViewport}
              targetTracks={lprState.targetTracks}
              analysisTrack={lprAnalysisTrack}
              selectedTargetTrackId={lprState.selectedTargetTrackId}
              liveTransportStore={liveTransportStore}
              onSelectTrack={handleSelectTargetTrack}
            />
            {activeFile.markerRect && markerStyle && (
              <div
                className={styles.previewMarker}
                style={markerStyle}
                onPointerDown={handleMarkerPointerDown}
              >
                <button
                  type="button"
                  className={styles.previewMarkerResize}
                  onPointerDown={handleMarkerResizePointerDown}
                  aria-label="Resize marker"
                />
              </div>
            )}
          </div>
        )}

        <div className={styles.previewTools}>
          <button type="button" className={styles.previewToolButton} onClick={handleCreateMarker} disabled={!activeFile}>
            <Square size={14} />
            {activeFile?.markerRect ? 'Marker' : 'Add Marker'}
          </button>
          <button type="button" className={styles.previewToolButton} onClick={() => dispatch({ type: 'clear-marker' })} disabled={!activeFile?.markerRect}>
            <X size={14} />
            Clear
          </button>
        </div>
      </div>
    </section>
  );
};
