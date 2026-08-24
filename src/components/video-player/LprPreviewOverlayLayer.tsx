import React, { useMemo, useSyncExternalStore } from 'react';
import { clampNormalizedRect, findClosestTrackFrame, resolveTrackFrameAtPlayhead } from '../../modules/editor/domain/model';
import { EDITOR_ENV } from '../../shared/config/editorEnv';
import type { LprTargetTrack, LprTrackedRegion } from '../../shared/contracts';
import type { LiveTransportStore } from '../../modules/editor/application/liveTransport';
import type { PreviewViewport } from './useVideoViewport';
import styles from '../workspace/MainWorkspace.module.css';

type LprOverlayTargetEntry = {
  trackId: string;
  label: string;
  selectionTrackId: string | null;
  isSelected: boolean;
  frame: LprTrackedRegion;
};

export type LprOverlayLayerProps = {
  previewViewport: PreviewViewport;
  targetTracks: LprTargetTrack[];
  analysisTrack: LprTargetTrack | null;
  selectedTargetTrackId: string | null;
  liveTransportStore: LiveTransportStore;
  onSelectTrack: (targetTrackId: string, preferredTimeMs?: number | null) => void;
};

export const LprOverlayTargetButton = React.memo(function LprOverlayTargetButton({
  entry,
  previewViewport,
  onSelectTrack,
}: {
  entry: LprOverlayTargetEntry;
  previewViewport: PreviewViewport;
  onSelectTrack: (targetTrackId: string, preferredTimeMs?: number | null) => void;
}) {
  const box = clampNormalizedRect(entry.frame.box);
  const overlayStyle = {
    width: `${box.width * previewViewport.width}px`,
    height: `${box.height * previewViewport.height}px`,
    transform: `translate3d(${previewViewport.left + (box.x * previewViewport.width)}px, ${previewViewport.top + (box.y * previewViewport.height)}px, 0)`,
  } satisfies React.CSSProperties;

  return (
    <button
      type="button"
      className={`${styles.lprOverlayTarget} ${entry.isSelected ? styles.lprOverlayTargetSelected : ''}`}
      style={overlayStyle}
      onClick={() => entry.selectionTrackId && onSelectTrack(entry.selectionTrackId, entry.frame.timeMs)}
    >
      <span className={styles.lprOverlayLabel}>{entry.label}</span>
    </button>
  );
});

export const LprPreviewOverlayLayer = React.memo(function LprPreviewOverlayLayer({
  previewViewport,
  targetTracks,
  analysisTrack,
  selectedTargetTrackId,
  liveTransportStore,
  onSelectTrack,
}: LprOverlayLayerProps) {
  const liveTransport = useSyncExternalStore(
    liveTransportStore.subscribe,
    liveTransportStore.getSnapshot,
    liveTransportStore.getSnapshot,
  );

  const overlayEntries = useMemo<LprOverlayTargetEntry[]>(() => {
    const targetLabels = new Map(targetTracks.map((track) => [track.id, track.label]));
    return [
      ...targetTracks
        .filter((track) => track.id !== analysisTrack?.id)
        .flatMap((track) => {
          const frame = findClosestTrackFrame(track, liveTransport.playheadMs, EDITOR_ENV.lprTargetOverlayToleranceMs);
          if (!frame) {
            return [];
          }
          return [{
            trackId: track.id,
            label: track.label,
            selectionTrackId: track.id,
            isSelected: track.id === selectedTargetTrackId,
            frame,
          }];
        }),
      ...(analysisTrack ? (() => {
        const frame = resolveTrackFrameAtPlayhead(
          analysisTrack,
          liveTransport.playheadMs,
          EDITOR_ENV.lprTargetOverlayToleranceMs,
          EDITOR_ENV.lprAnalysisInterpolationGapMs,
        );
        if (!frame) {
          return [];
        }
        return [{
          trackId: analysisTrack.id,
          label: targetLabels.get(selectedTargetTrackId ?? '') ?? analysisTrack.label,
          selectionTrackId: selectedTargetTrackId ?? analysisTrack.id,
          isSelected: (selectedTargetTrackId ?? analysisTrack.id) === selectedTargetTrackId,
          frame,
        } satisfies LprOverlayTargetEntry];
      })() : []),
    ];
  }, [analysisTrack, liveTransport.playheadMs, selectedTargetTrackId, targetTracks]);

  if (previewViewport.width <= 0) {
    return null;
  }

  return (
    <>
      {overlayEntries.map((entry) => (
        <LprOverlayTargetButton
          key={entry.trackId}
          entry={entry}
          previewViewport={previewViewport}
          onSelectTrack={onSelectTrack}
        />
      ))}
    </>
  );
});
